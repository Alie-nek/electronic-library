from flask import session, flash, redirect, url_for, request
from functools import wraps
import hashlib
from db import get_db_connection

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain, hashed):
    return hash_password(plain) == hashed

def get_current_user():
    if 'user_id' not in session:
        return None
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT u.*, r.name as role_name 
        FROM users u 
        JOIN roles r ON u.role_id = r.id 
        WHERE u.id = %s
    ''', (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Для выполнения данного действия необходимо пройти процедуру аутентификации', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user or user['role_name'] not in allowed_roles:
                flash('У вас недостаточно прав для выполнения данного действия', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator