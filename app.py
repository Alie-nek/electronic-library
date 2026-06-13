from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, jsonify
import hashlib
import os
import bleach
import markdown
from datetime import datetime, timedelta
import csv
from io import StringIO
import uuid

from config import Config
from db import get_db_connection, init_db
from auth import login_required, role_required, get_current_user, hash_password, verify_password

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

init_db()


def save_cover(file, book_id):
    if not file or file.filename == '':
        return None
    
    file_data = file.read()
    md5_hash = hashlib.md5(file_data).hexdigest()
    
    conn = get_db_connection()
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, filename FROM covers WHERE md5_hash = %s LIMIT 1", (md5_hash,))
    existing = cursor.fetchone()
    cursor.close()
    
    if existing:
        filename = existing['filename']
        
        cursor2 = conn.cursor(dictionary=True)
        try:
            cursor2.execute(
                "INSERT INTO covers (filename, mime_type, md5_hash, book_id) VALUES (%s, %s, %s, %s)",
                (filename, file.mimetype, md5_hash, book_id)
            )
            cover_id = cursor2.lastrowid
            conn.commit()
        except Exception:
            conn.rollback()
            cursor2.execute("SELECT id FROM covers WHERE md5_hash = %s LIMIT 1", (md5_hash,))
            cover_id = cursor2.fetchone()['id']
            conn.commit()
        finally:
            cursor2.close()
            conn.close()
            return cover_id
    
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
    filename = f"{book_id}_{md5_hash[:8]}.{ext}"
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename).replace('\\', '/')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    with open(filepath, 'wb') as f:
        f.write(file_data)
    
    db_filename = filename.replace('\\', '/')
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "INSERT INTO covers (filename, mime_type, md5_hash, book_id) VALUES (%s, %s, %s, %s)",
        (db_filename, file.mimetype, md5_hash, book_id)
    )
    cover_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return cover_id

def record_book_view(book_id, user_id=None):
    session_id = session.get('temp_id')
    if not session_id:
        session_id = str(uuid.uuid4())
        session['temp_id'] = session_id
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    today = datetime.now().date()
    
    if user_id:
        cursor.execute(
            "SELECT COUNT(*) FROM book_views WHERE book_id = %s AND user_id = %s AND DATE(view_date) = %s",
            (book_id, user_id, today)
        )
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM book_views WHERE book_id = %s AND session_id = %s AND DATE(view_date) = %s",
            (book_id, session_id, today)
        )
    
    count = cursor.fetchone()[0]
    
    if count < 10:
        if user_id:
            cursor.execute(
                "INSERT INTO book_views (book_id, user_id, session_id) VALUES (%s, %s, %s)",
                (book_id, user_id, session_id)
            )
        else:
            cursor.execute(
                "INSERT INTO book_views (book_id, session_id) VALUES (%s, %s)",
                (book_id, session_id)
            )
        conn.commit()
    
    cursor.close()
    conn.close()

def get_popular_books(limit=5):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    three_months_ago = datetime.now() - timedelta(days=90)
    
    cursor.execute('''
        SELECT b.id, b.title, COUNT(bv.id) as views_count
        FROM books b
        JOIN book_views bv ON b.id = bv.book_id
        WHERE bv.view_date >= %s
        GROUP BY b.id
        ORDER BY views_count DESC
        LIMIT %s
    ''', (three_months_ago, limit))
    
    books = cursor.fetchall()
    cursor.close()
    conn.close()
    return books

def get_recently_viewed_books(user_id, limit=5):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    session_id = session.get('temp_id')
    books = []
    
    if user_id:
        cursor.execute('''
            SELECT DISTINCT b.id, b.title, MAX(bv.view_date) as last_view
            FROM books b
            JOIN book_views bv ON b.id = bv.book_id
            WHERE bv.user_id = %s
            GROUP BY b.id
            ORDER BY last_view DESC
            LIMIT %s
        ''', (user_id, limit))
        books = cursor.fetchall()
    elif session_id:
        cursor.execute('''
            SELECT DISTINCT b.id, b.title, MAX(bv.view_date) as last_view
            FROM books b
            JOIN book_views bv ON b.id = bv.book_id
            WHERE bv.session_id = %s
            GROUP BY b.id
            ORDER BY last_view DESC
            LIMIT %s
        ''', (session_id, limit))
        books = cursor.fetchall()
    
    cursor.close()
    conn.close()
    return books


@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute('''
        SELECT b.*, 
               (SELECT AVG(rating) FROM reviews WHERE book_id = b.id) as avg_rating,
               (SELECT COUNT(*) FROM reviews WHERE book_id = b.id) as reviews_count,
               GROUP_CONCAT(DISTINCT g.name SEPARATOR ', ') as genres,
               (SELECT filename FROM covers WHERE book_id = b.id LIMIT 1) as cover_filename
        FROM books b
        LEFT JOIN book_genres bg ON b.id = bg.book_id
        LEFT JOIN genres g ON bg.genre_id = g.id
        GROUP BY b.id
        ORDER BY b.year DESC, b.id DESC
        LIMIT %s OFFSET %s
    ''', (per_page, offset))
    
    books = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) as total FROM books")
    total = cursor.fetchone()['total']
    
    cursor.close()
    conn.close()
    
    user = get_current_user()
    popular_books = get_popular_books(5)
    recently_viewed = get_recently_viewed_books(user['id'] if user else None, 5)
    
    return render_template('index.html', 
                         books=books, 
                         page=page, 
                         total=total, 
                         per_page=per_page,
                         user=user,
                         popular_books=popular_books,
                         recently_viewed=recently_viewed)

@app.route('/book/<int:book_id>')
def book_detail(book_id):
    user = get_current_user()
    
    record_book_view(book_id, user['id'] if user else None)
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute('''
        SELECT b.*, c.filename as cover_filename
        FROM books b
        LEFT JOIN covers c ON b.id = c.book_id
        WHERE b.id = %s
    ''', (book_id,))
    book = cursor.fetchone()
    
    if not book:
        flash('Книга не найдена', 'danger')
        return redirect(url_for('index'))
    
    cursor.execute('''
        SELECT g.name FROM genres g
        JOIN book_genres bg ON g.id = bg.genre_id
        WHERE bg.book_id = %s
    ''', (book_id,))
    book['genres_list'] = [g['name'] for g in cursor.fetchall()]
    
    cursor.execute('''
        SELECT r.*, u.last_name, u.first_name, u.middle_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.book_id = %s
        ORDER BY r.created_at DESC
    ''', (book_id,))
    reviews = cursor.fetchall()
    
    user_review = None
    if user:
        cursor.execute('SELECT * FROM reviews WHERE book_id = %s AND user_id = %s', (book_id, user['id']))
        user_review = cursor.fetchone()
        if user_review:
            user_review['text_html'] = markdown.markdown(user_review['text'])
    
    cursor.close()
    conn.close()
    
    book['description_html'] = markdown.markdown(book['description'])
    for review in reviews:
        review['text_html'] = markdown.markdown(review['text'])
        full_name = f"{review['last_name']} {review['first_name']}"
        if review['middle_name']:
            full_name += f" {review['middle_name']}"
        review['user_fullname'] = full_name
    
    return render_template('book_detail.html', 
                         book=book, 
                         reviews=reviews, 
                         user=user,
                         user_review=user_review)

@app.route('/book/add', methods=['GET', 'POST'])
@login_required
@role_required(['admin'])
def add_book():
    user = get_current_user()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM genres ORDER BY name")
    all_genres = cursor.fetchall()
    
    if request.method == 'POST':
        title = request.form['title']
        description = bleach.clean(request.form['description'], strip=True)
        year = request.form['year']
        publisher = request.form['publisher']
        author = request.form['author']
        pages = request.form['pages']
        genre_ids = request.form.getlist('genres')
        cover_file = request.files.get('cover')
        
        try:
            cursor.execute('''
                INSERT INTO books (title, description, year, publisher, author, pages)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (title, description, year, publisher, author, pages))
            book_id = cursor.lastrowid
            
            for gid in genre_ids:
                cursor.execute('INSERT INTO book_genres (book_id, genre_id) VALUES (%s, %s)', (book_id, gid))
            
            conn.commit()
            
            if cover_file and cover_file.filename:
                save_cover(cover_file, book_id)
            
            flash('Книга успешно добавлена', 'success')
            return redirect(url_for('book_detail', book_id=book_id))
            
        except Exception as e:
            conn.rollback()
            flash(f'При сохранении данных возникла ошибка: {str(e)}', 'danger')
    
    cursor.close()
    conn.close()
    return render_template('book_form.html', book=None, genres=all_genres, user=user)

@app.route('/book/<int:book_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'moderator'])
def edit_book(book_id):
    user = get_current_user()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM books WHERE id = %s", (book_id,))
    book = cursor.fetchone()
    if not book:
        flash('Книга не найдена', 'danger')
        return redirect(url_for('index'))
    
    cursor.execute("SELECT * FROM genres ORDER BY name")
    all_genres = cursor.fetchall()
    
    cursor.execute("SELECT genre_id FROM book_genres WHERE book_id = %s", (book_id,))
    selected_genres = [str(g['genre_id']) for g in cursor.fetchall()]
    
    if request.method == 'POST':
        title = request.form['title']
        description = bleach.clean(request.form['description'], strip=True)
        year = request.form['year']
        publisher = request.form['publisher']
        author = request.form['author']
        pages = request.form['pages']
        genre_ids = request.form.getlist('genres')
        
        try:
            cursor.execute('''
                UPDATE books SET title=%s, description=%s, year=%s, publisher=%s, author=%s, pages=%s 
                WHERE id=%s
            ''', (title, description, year, publisher, author, pages, book_id))
            
            cursor.execute("DELETE FROM book_genres WHERE book_id = %s", (book_id,))
            for gid in genre_ids:
                cursor.execute('INSERT INTO book_genres (book_id, genre_id) VALUES (%s, %s)', (book_id, gid))
            
            conn.commit()
            flash('Книга успешно обновлена', 'success')
            return redirect(url_for('book_detail', book_id=book_id))
            
        except Exception as e:
            conn.rollback()
            flash(f'При сохранении данных возникла ошибка: {str(e)}', 'danger')
    
    cursor.close()
    conn.close()
    return render_template('book_form.html', book=book, genres=all_genres, 
                         selected_genres=selected_genres, user=user)

@app.route('/book/<int:book_id>/delete', methods=['POST'])
@login_required
@role_required(['admin'])
def delete_book(book_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT filename FROM covers WHERE book_id = %s", (book_id,))
    cover = cursor.fetchone()
    
    cursor.execute("DELETE FROM books WHERE id = %s", (book_id,))
    conn.commit()
    
    if cover and cover[0]:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], cover[0])
        if os.path.exists(filepath):
            os.remove(filepath)
    
    cursor.close()
    conn.close()
    
    flash('Книга успешно удалена', 'success')
    return redirect(url_for('index'))

@app.route('/book/<int:book_id>/review', methods=['GET', 'POST'])
@login_required
@role_required(['user', 'moderator', 'admin'])
def add_review(book_id):
    user = get_current_user()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM reviews WHERE book_id = %s AND user_id = %s", (book_id, user['id']))
    if cursor.fetchone():
        flash('Вы уже оставили рецензию на эту книгу', 'warning')
        return redirect(url_for('book_detail', book_id=book_id))
    
    cursor.execute("SELECT id, title FROM books WHERE id = %s", (book_id,))
    book = cursor.fetchone()
    
    if request.method == 'POST':
        rating = int(request.form['rating'])
        text = bleach.clean(request.form['text'], strip=True)
        
        try:
            cursor.execute('''
                INSERT INTO reviews (book_id, user_id, rating, text)
                VALUES (%s, %s, %s, %s)
            ''', (book_id, user['id'], rating, text))
            conn.commit()
            flash('Рецензия успешно добавлена', 'success')
            return redirect(url_for('book_detail', book_id=book_id))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при сохранении рецензии: {str(e)}', 'danger')
    
    cursor.close()
    conn.close()
    return render_template('review_form.html', book=book, user=user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login = request.form['login']
        password = request.form['password']
        remember = request.form.get('remember')
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM users WHERE login = %s', (login,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and verify_password(password, user['password_hash']):
            session['user_id'] = user['id']
            if remember:
                session.permanent = True
            flash('Вы успешно вошли в систему', 'success')
            next_url = request.args.get('next')
            return redirect(next_url or url_for('index'))
        else:
            flash('Невозможно аутентифицироваться с указанными логином и паролем', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

@app.route('/statistics')
@login_required
@role_required(['admin'])
def statistics():
    user = get_current_user()
    return render_template('statistics.html', user=user)

@app.route('/api/user-actions-log')
@login_required
@role_required(['admin'])
def api_user_actions_log():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute('''
        SELECT bv.id, 
               CONCAT(COALESCE(u.last_name, ''), ' ', COALESCE(u.first_name, ''), ' ', COALESCE(u.middle_name, '')) as user_fullname,
               b.title as book_title,
               bv.view_date
        FROM book_views bv
        LEFT JOIN users u ON bv.user_id = u.id
        JOIN books b ON bv.book_id = b.id
        ORDER BY bv.view_date DESC
        LIMIT %s OFFSET %s
    ''', (per_page, offset))
    
    logs = cursor.fetchall()
    for log in logs:
        if not log['user_fullname'] or log['user_fullname'].strip() == '':
            log['user_fullname'] = 'Неаутентифицированный пользователь'
    
    cursor.execute("SELECT COUNT(*) as total FROM book_views")
    total = cursor.fetchone()['total']
    
    cursor.close()
    conn.close()
    
    return jsonify({'data': logs, 'total': total, 'page': page, 'per_page': per_page})

@app.route('/api/book-stats')
@login_required
@role_required(['admin'])
def api_book_stats():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = '''
        SELECT b.id, b.title, COUNT(bv.id) as views_count
        FROM books b
        JOIN book_views bv ON b.id = bv.book_id
        WHERE bv.user_id IS NOT NULL
    '''
    params = []
    
    if date_from:
        query += " AND DATE(bv.view_date) >= %s"
        params.append(date_from)
    if date_to:
        query += " AND DATE(bv.view_date) <= %s"
        params.append(date_to)
    
    query += " GROUP BY b.id ORDER BY views_count DESC LIMIT %s OFFSET %s"
    params.extend([per_page, offset])
    
    cursor.execute(query, params)
    stats = cursor.fetchall()
    
    count_query = '''
        SELECT COUNT(DISTINCT b.id) as total
        FROM books b
        JOIN book_views bv ON b.id = bv.book_id
        WHERE bv.user_id IS NOT NULL
    '''
    cursor.execute(count_query)
    total = cursor.fetchone()['total']
    
    cursor.close()
    conn.close()
    
    return jsonify({'data': stats, 'total': total, 'page': page, 'per_page': per_page})

@app.route('/export/csv/<entity>')
@login_required
@role_required(['admin'])
def export_csv(entity):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    output = StringIO()
    writer = csv.writer(output, delimiter=';')
    
    if entity == 'user_actions':
        writer.writerow(['№', 'ФИО пользователя', 'Название книги', 'Дата и время просмотра'])
        cursor.execute('''
            SELECT 
                CASE 
                    WHEN u.id IS NULL THEN 'Неаутентифицированный пользователь'
                    ELSE CONCAT(COALESCE(u.last_name, ''), ' ', COALESCE(u.first_name, ''), ' ', COALESCE(u.middle_name, ''))
                END as user_fullname,
                b.title as book_title, 
                bv.view_date
            FROM book_views bv
            LEFT JOIN users u ON bv.user_id = u.id
            JOIN books b ON bv.book_id = b.id
            ORDER BY bv.view_date DESC
        ''')
        rows = cursor.fetchall()
        for idx, row in enumerate(rows, 1):
            writer.writerow([idx, row['user_fullname'].strip(), row['book_title'], row['view_date']])
    
    elif entity == 'book_stats':
        writer.writerow(['№', 'Название книги', 'Количество просмотров'])
        
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        query = '''
            SELECT b.title, COUNT(bv.id) as views_count
            FROM books b
            JOIN book_views bv ON b.id = bv.book_id
            WHERE bv.user_id IS NOT NULL
        '''
        params = []
        
        if date_from:
            query += " AND DATE(bv.view_date) >= %s"
            params.append(date_from)
        if date_to:
            query += " AND DATE(bv.view_date) <= %s"
            params.append(date_to)
        
        query += " GROUP BY b.id ORDER BY views_count DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        for idx, row in enumerate(rows, 1):
            writer.writerow([idx, row['title'], row['views_count']])
    
    cursor.close()
    conn.close()
    
    output.seek(0)
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{entity}_{date_str}.csv"
    
    content = output.getvalue()
    content_with_bom = '\ufeff' + content
    
    response = make_response(content_with_bom)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@app.template_filter('pluralize_views')
def pluralize_views(count):
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} просмотр"
    elif count % 10 in [2,3,4] and count % 100 not in [12,13,14]:
        return f"{count} просмотра"
    else:
        return f"{count} просмотров"

@app.route('/static/<path:filename>')
def serve_static(filename):
    from flask import send_from_directory
    return send_from_directory('static', filename)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
