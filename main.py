"""
Payroll Management System (simple, self-contained)
Features:
- SQLite persistence for employee records and payslips
- Add / update / delete / list employees
- Compute salary with basic components (Basic, HRA, DA, Allowances) and deductions (PF, Tax)
- Generate plain-text payslip and save to DB
- Export payslips to CSV

Usage:
$ python3 payroll_system.py

This script is intentionally simple and easy to extend.
"""
from decimal import Decimal, ROUND_HALF_UP
import sqlite3
import datetime
import csv
import os
import sys

DB_FILE = 'payroll.db'


def to_decimal(x):
    return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def init_db(db_file=DB_FILE):
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code TEXT UNIQUE,
            name TEXT,
            designation TEXT,
            basic REAL,
            hra_percent REAL,
            da_percent REAL,
            other_allowances REAL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS payslips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id INTEGER,
            month TEXT,
            generated_on TEXT,
            gross_salary REAL,
            total_deductions REAL,
            net_salary REAL,
            breakdown TEXT,
            FOREIGN KEY(emp_id) REFERENCES employees(id)
        )
    ''')
    conn.commit()
    return conn


def add_employee(conn, emp_code, name, designation, basic, hra_percent=20, da_percent=0, other_allowances=0):
    cur = conn.cursor()
    try:
        cur.execute('''INSERT INTO employees (emp_code,name,designation,basic,hra_percent,da_percent,other_allowances)
                       VALUES (?,?,?,?,?,?,?)''',
                    (emp_code, name, designation, float(basic), float(hra_percent), float(da_percent), float(other_allowances)))
        conn.commit()
        print('Employee added.')
    except sqlite3.IntegrityError:
        print('Error: emp_code must be unique.')

def update_employee(conn, emp_code, **kwargs):
    cur = conn.cursor()
    fields = []
    values = []
    for k, v in kwargs.items():
        if v is not None:
            fields.append(f"{k} = ?")
            values.append(v)
    if not fields:
        print('No updates provided.')
        return
    values.append(emp_code)
    sql = f"UPDATE employees SET {', '.join(fields)} WHERE emp_code = ?"
    cur.execute(sql, values)
    conn.commit()
    print('Employee updated.')

def delete_employee(conn, emp_code):
    cur = conn.cursor()
    cur.execute('DELETE FROM employees WHERE emp_code = ?', (emp_code,))
    conn.commit()
    print('Employee deleted (if existed).')

def list_employees(conn):
    cur = conn.cursor()
    cur.execute('SELECT emp_code, name, designation, basic FROM employees ORDER BY name')
    rows = cur.fetchall()
    if not rows:
        print('No employees found.')
        return
    print('\nEmployees:')
    for r in rows:
        print(f"Code: {r[0]} | Name: {r[1]} | Designation: {r[2]} | Basic: {to_decimal(r[3])}")
    print()

def get_employee_by_code(conn, emp_code):
    cur = conn.cursor()
    cur.execute('SELECT id, emp_code, name, designation, basic, hra_percent, da_percent, other_allowances FROM employees WHERE emp_code = ?', (emp_code,))
    row = cur.fetchone()
    return row



PF_PERCENT = Decimal('12.0')  
TAX_SLABS = [
    (Decimal('250000'), Decimal('0.0')),
    (Decimal('500000'), Decimal('0.05')),
    (Decimal('1000000'), Decimal('0.2')),
    (Decimal('999999999'), Decimal('0.3')),
]

def income_tax_annually(taxable_income):
   
    tax = Decimal('0')
    prev_limit = Decimal('0')
    for limit, rate in TAX_SLABS:
        slab_amount = min(limit - prev_limit, taxable_income - prev_limit)
        if slab_amount <= 0:
            prev_limit = limit
            continue
        tax += slab_amount * rate
        prev_limit = limit
        if taxable_income <= limit:
            break
    return to_decimal(tax)

def compute_pay(conn, emp_code, month=None):
    row = get_employee_by_code(conn, emp_code)
    if not row:
        raise ValueError('Employee not found')
    emp_id, code, name, designation, basic, hra_pct, da_pct, other_allow = row
    basic = to_decimal(basic)
    hra = (basic * to_decimal(hra_pct) / Decimal('100')).quantize(Decimal('0.01'))
    da = (basic * to_decimal(da_pct) / Decimal('100')).quantize(Decimal('0.01'))
    other_allow = to_decimal(other_allow)
    gross = (basic + hra + da + other_allow).quantize(Decimal('0.01'))

    pf = (basic * PF_PERCENT / Decimal('100')).quantize(Decimal('0.01'))

    annual_gross = gross * Decimal('12')
    
    standard_deduction = Decimal('50000')
    taxable_ann = max(Decimal('0'), annual_gross - standard_deduction)
    annual_tax = income_tax_annually(taxable_ann)
    monthly_tax = (annual_tax / Decimal('12')).quantize(Decimal('0.01'))

    total_deductions = (pf + monthly_tax).quantize(Decimal('0.01'))
    net = (gross - total_deductions).quantize(Decimal('0.01'))

    breakdown = {
        'basic': str(basic),
        'hra': str(hra),
        'da': str(da),
        'other_allowances': str(other_allow),
        'gross_salary': str(gross),
        'pf': str(pf),
        'tax': str(monthly_tax),
        'total_deductions': str(total_deductions),
        'net_salary': str(net)
    }

    if month is None:
        month = datetime.datetime.now().strftime('%Y-%m')

   
    cur = conn.cursor()
    cur.execute('''INSERT INTO payslips (emp_id, month, generated_on, gross_salary, total_deductions, net_salary, breakdown)
                   VALUES (?,?,?,?,?,?,?)''',
                (emp_id, month, datetime.datetime.now().isoformat(), float(gross), float(total_deductions), float(net), str(breakdown)))
    conn.commit()

    return {
        'emp_code': code,
        'name': name,
        'designation': designation,
        'month': month,
        **breakdown
    }


def generate_payslip_text(p):
    lines = []
    lines.append('--- PAYSLIP ---')
    lines.append(f"Employee Code: {p['emp_code']}")
    lines.append(f"Name: {p['name']}")
    lines.append(f"Designation: {p['designation']}")
    lines.append(f"Month: {p['month']}")
    lines.append('')
    lines.append(f"Basic: {p['basic']}")
    lines.append(f"HRA: {p['hra']}")
    lines.append(f"DA: {p['da']}")
    lines.append(f"Other Allowances: {p['other_allowances']}")
    lines.append(f"Gross Salary: {p['gross_salary']}")
    lines.append('')
    lines.append('Deductions:')
    lines.append(f"PF: {p['pf']}")
    lines.append(f"Tax: {p['tax']}")
    lines.append(f"Total Deductions: {p['total_deductions']}")
    lines.append('')
    lines.append(f"NET PAY: {p['net_salary']}")
    return '\n'.join(lines)

def export_payslips_csv(conn, filename='payslips_export.csv'):
    cur = conn.cursor()
    cur.execute('SELECT p.id, e.emp_code, e.name, p.month, p.gross_salary, p.total_deductions, p.net_salary, p.generated_on FROM payslips p JOIN employees e ON e.id = p.emp_id ORDER BY p.generated_on')
    rows = cur.fetchall()
    if not rows:
        print('No payslips to export.')
        return
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['payslip_id','emp_code','name','month','gross_salary','total_deductions','net_salary','generated_on'])
        for r in rows:
            writer.writerow(r)
    print(f'Exported {len(rows)} payslips to {filename}')


def main_menu(conn):
    while True:
        print('\nPayroll Management System')
        print('1) Add employee')
        print('2) Update employee')
        print('3) Delete employee')
        print('4) List employees')
        print('5) Generate payslip')
        print('6) Export payslips to CSV')
        print('7) Quit')
        choice = input('Choose an option: ').strip()
        if choice == '1':
            emp_code = input('Employee code: ').strip()
            name = input('Name: ').strip()
            desig = input('Designation: ').strip()
            basic = input('Basic salary: ').strip()
            hra = input('HRA percent (default 20): ').strip() or '20'
            da = input('DA percent (default 0): ').strip() or '0'
            other = input('Other allowances (default 0): ').strip() or '0'
            add_employee(conn, emp_code, name, desig, to_decimal(basic), hra, da, other)
        elif choice == '2':
            code = input('Employee code to update: ').strip()
            print('Leave a field blank to keep current value')
            name = input('New name: ').strip() or None
            desig = input('New designation: ').strip() or None
            basic = input('New basic (number): ').strip() or None
            hra = input('New HRA percent: ').strip() or None
            da = input('New DA percent: ').strip() or None
            other = input('New other allowances: ').strip() or None
            kwargs = {}
            if name is not None: kwargs['name'] = name
            if desig is not None: kwargs['designation'] = desig
            if basic is not None: kwargs['basic'] = float(basic)
            if hra is not None: kwargs['hra_percent'] = float(hra)
            if da is not None: kwargs['da_percent'] = float(da)
            if other is not None: kwargs['other_allowances'] = float(other)
            update_employee(conn, code, **kwargs)
        elif choice == '3':
            code = input('Employee code to delete: ').strip()
            delete_employee(conn, code)
        elif choice == '4':
            list_employees(conn)
        elif choice == '5':
            code = input('Employee code for payslip: ').strip()
            month = input('Month (YYYY-MM) or leave blank for current: ').strip() or None
            try:
                payslip = compute_pay(conn, code, month)
                text = generate_payslip_text(payslip)
                print('\n' + text + '\n')
                save_file = input('Save payslip to file? (y/N): ').strip().lower()
                if save_file == 'y':
                    filename = f"payslip_{code}_{payslip['month']}.txt"
                    with open(filename, 'w') as f:
                        f.write(text)
                    print(f'Saved to {filename}')
            except Exception as e:
                print('Error:', e)
        elif choice == '6':
            fname = input('CSV filename (default payslips_export.csv): ').strip() or 'payslips_export.csv'
            export_payslips_csv(conn, fname)
        elif choice == '7':
            print('Goodbye')
            break
        else:
            print('Invalid choice')

if __name__ == '__main__':
    conn = init_db()
    try:
        main_menu(conn)
        
       
    finally:
        conn.close()
