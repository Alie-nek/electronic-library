import mysql.connector
from mysql.connector import Error
import os
import re

def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        from config import Config
        return mysql.connector.connect(
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE,
            autocommit=False,
            use_pure=True
        )
   
    pattern = r'mysql://([^:]+):([^@]+)@([^:]+):(\d+)/([^?]+)'
    match = re.match(pattern, database_url)
    
    if not match:
        raise Exception(f"Не удалось распарсить DATABASE_URL: {database_url[:50]}...")
    
    user, password, host, port, database = match.groups()
    
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=int(port),
        autocommit=False,
        use_pure=True,
        ssl_disabled=False  
    )

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS books (
            id INT PRIMARY KEY AUTO_INCREMENT,
            title VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            year YEAR NOT NULL,
            publisher VARCHAR(255) NOT NULL,
            author VARCHAR(255) NOT NULL,
            pages INT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS genres (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS book_genres (
            book_id INT,
            genre_id INT,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
            FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE CASCADE,
            PRIMARY KEY (book_id, genre_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS covers (
            id INT PRIMARY KEY AUTO_INCREMENT,
            filename VARCHAR(255) NOT NULL,
            mime_type VARCHAR(100) NOT NULL,
            md5_hash VARCHAR(32) NOT NULL,
            book_id INT NOT NULL,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
            INDEX idx_md5_hash (md5_hash)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS roles (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(50) NOT NULL UNIQUE,
            description TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INT PRIMARY KEY AUTO_INCREMENT,
            login VARCHAR(100) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            last_name VARCHAR(100) NOT NULL,
            first_name VARCHAR(100) NOT NULL,
            middle_name VARCHAR(100),
            role_id INT NOT NULL,
            FOREIGN KEY (role_id) REFERENCES roles(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INT PRIMARY KEY AUTO_INCREMENT,
            book_id INT NOT NULL,
            user_id INT NOT NULL,
            rating INT NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE KEY unique_review (book_id, user_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS book_views (
            id INT PRIMARY KEY AUTO_INCREMENT,
            book_id INT NOT NULL,
            user_id INT NULL,
            session_id VARCHAR(100) NULL,
            view_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
            INDEX idx_book_date (book_id, view_date),
            INDEX idx_user_date (user_id, view_date),
            INDEX idx_session_date (session_id, view_date)
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM roles")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO roles (name, description) VALUES ('admin', 'Администратор - полный доступ')")
        cursor.execute("INSERT INTO roles (name, description) VALUES ('moderator', 'Модератор - может редактировать книги')")
        cursor.execute("INSERT INTO roles (name, description) VALUES ('user', 'Пользователь - может оставлять рецензии')")
    
    cursor.execute("SELECT COUNT(*) FROM genres")
    if cursor.fetchone()[0] == 0:
        genres = ['Роман', 'Детектив', 'Фантастика', 'Наука', 'Поэзия', 'Драма', 'Приключения', 'Триллер', 'История']
        for g in genres:
            cursor.execute("INSERT INTO genres (name) VALUES (%s)", (g,))
    
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        import hashlib
        
        cursor.execute("SELECT id FROM roles WHERE name = 'admin'")
        admin_role_id = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM roles WHERE name = 'moderator'")
        moderator_role_id = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM roles WHERE name = 'user'")
        user_role_id = cursor.fetchone()[0]
        
        users = [
            ('admin', hashlib.sha256('admin123'.encode()).hexdigest(), 'Администратор', 'Системный', None, admin_role_id),
            ('moderator', hashlib.sha256('moder123'.encode()).hexdigest(), 'Модератор', 'Мария', 'Викторовна', moderator_role_id),
            ('user', hashlib.sha256('user123'.encode()).hexdigest(), 'Пользователь', 'Обычный', None, user_role_id),
        ]
        
        for user in users:
            cursor.execute('''
                INSERT INTO users (login, password_hash, last_name, first_name, middle_name, role_id) 
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', user)
    
    conn.commit()
    cursor.close()
    conn.close()