import re

from app import app
from models import Employee, User, School, db
from werkzeug.security import generate_password_hash

with app.test_client() as client:
    print('='*60)
    print('COMPREHENSIVE LOCAL FEATURE TEST')
    print('='*60)
    
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', is_admin=True, must_change_password=False)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        else:
            admin.set_password('admin123')
            admin.must_change_password = False
            db.session.commit()
        
        school = School.query.filter_by(name='Test School').first()
        if not school:
            school = School(name='Test School', latitude=18.5, longitude=73.8, geofence_radius=100)
            db.session.add(school)
            db.session.commit()
        
        emp = Employee.query.filter_by(phone='9876543210').first()
        if not emp:
            emp = Employee(emp_id='EMP001', name='Test Employee', phone='9876543210', is_active=True, is_approved=True)
            db.session.add(emp)
            db.session.commit()
            emp.schools.append(school)
            db.session.commit()
        emp.is_approved = True
        emp.is_active = True
        db.session.commit()
        
        portal_user = User.query.filter_by(employee_id=emp.id).first()
        if not portal_user:
            portal_user = User(username='emp_1', employee_id=emp.id, is_admin=False)
            db.session.add(portal_user)
        portal_user.set_password('test123')
        db.session.commit()
        print(f'Employee ID: {emp.id}, Portal User ID: {portal_user.id}')
    
    print()
    print('=== ADMIN PANEL TESTS ===')
    print()
    
    print('1. Admin login:', end=' ')
    r = client.get('/login')
    csrf_match = re.search(r'csrf_token.*value="([^"]+)"', r.data.decode('utf-8'))
    csrf = csrf_match.group(1) if csrf_match else ''
    r = client.post('/login', data={'username': 'admin', 'password': 'admin123', 'csrf_token': csrf}, follow_redirects=True)
    print(f'OK (status={r.status_code})' if r.status_code == 200 and b'Dashboard' in r.data else f'FAIL (status={r.status_code})')
    
    print('2. Dashboard:', end=' ')
    r = client.get('/dashboard')
    print(f'OK (status={r.status_code})' if r.status_code == 200 and b'Active Employees' in r.data else f'FAIL (status={r.status_code})')
    
    print('3. Employees list:', end=' ')
    r = client.get('/employees')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('4. Add employee page:', end=' ')
    r = client.get('/employees/add')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('5. Attendance page:', end=' ')
    r = client.get('/attendance')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('6. Payroll page:', end=' ')
    r = client.get('/payroll')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('7. Schools page:', end=' ')
    r = client.get('/schools')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('8. Settings page:', end=' ')
    r = client.get('/settings')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('9. Departments page:', end=' ')
    r = client.get('/departments')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('10. Holidays page:', end=' ')
    r = client.get('/holidays')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('11. SMS panel:', end=' ')
    r = client.get('/sms')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('12. Advances page:', end=' ')
    r = client.get('/advances')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('13. Export employees:', end=' ')
    r = client.get('/export/employees')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('14. Logout:', end=' ')
    r = client.get('/logout', follow_redirects=True)
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print()
    print('=== EMPLOYEE PORTAL TESTS ===')
    print()
    
    print('15. Employee portal login:', end=' ')
    r = client.get('/portal/login')
    csrf_match = re.search(r'csrf_token.*value="([^"]+)"', r.data.decode('utf-8'))
    csrf = csrf_match.group(1) if csrf_match else ''
    r = client.post('/portal/login', data={'phone': '9876543210', 'password': 'test123', 'csrf_token': csrf}, follow_redirects=True)
    print(f'OK (status={r.status_code})' if r.status_code == 200 and b'Employee Portal' in r.data else f'FAIL (status={r.status_code})')
    
    print('16. Portal dashboard:', end=' ')
    r = client.get('/portal/dashboard')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('17. Portal punch:', end=' ')
    r = client.get('/portal/punch')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('18. Portal attendance:', end=' ')
    r = client.get('/portal/attendance')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('19. Portal leaves:', end=' ')
    r = client.get('/portal/leaves')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('20. Portal payslips:', end=' ')
    r = client.get('/portal/payslips')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print()
    print('=== API TESTS ===')
    print()
    
    print('21. JWT employee login:', end=' ')
    r = client.post('/api/v1/auth/login', json={'phone': '9876543210', 'password': 'test123'})
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    token = r.get_json().get('access_token') if r.status_code == 200 else None
    
    if token:
        print('22. JWT /me:', end=' ')
        r = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
        print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    else:
        print('22. JWT /me: SKIP (no token)')
    
    print('23. Punch without auth:', end=' ')
    client.get('/logout', follow_redirects=True)  # ensure no active session
    r = client.post('/api/punch', json={'lat': 18.5, 'lng': 73.8})
    print(f'OK (401 expected, got {r.status_code})' if r.status_code == 401 else f'UNEXPECTED (status={r.status_code})')
    
    print('24. Swagger UI:', end=' ')
    r = client.get('/api/docs/')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print('25. API spec JSON:', end=' ')
    r = client.get('/apispec_1.json')
    print(f'OK (status={r.status_code})' if r.status_code == 200 else f'FAIL (status={r.status_code})')
    
    print()
    print('='*60)
    print('TEST COMPLETE')
    print('='*60)
