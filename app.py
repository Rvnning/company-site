import io
import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file, flash
from supabase import create_client, Client
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from functools import wraps

# 1. 환경 변수 로드 (.env 파일 읽기)
load_dotenv()

app = Flask(__name__)

# 보안 설정 (Flask 세션 암호화 및 CSRF 방지)
app.secret_key = os.environ.get("SECRET_KEY", "default-fallback-secret-key")
csrf = CSRFProtect(app)

# 2. Supabase 클라이언트 초기화
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# 3. 관리자 권한 확인 데코레이터
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('관리자 권한이 필요합니다.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- [공개 페이지 라우팅] ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/inquiry', methods=['POST'])
def inquiry():
    # 고객 문의 데이터 수집 후 Supabase 'inquiries' 테이블에 저장
    company_name = request.form.get('company_name')
    manager_name = request.form.get('manager_name')
    phone = request.form.get('phone')
    email = request.form.get('email')
    content = request.form.get('content')
    
    if company_name and manager_name and phone and content:
        supabase.table('inquiries').insert({
            "company_name": company_name,
            "manager_name": manager_name,
            "phone": phone,
            "email": email,
            "content": content
        }).execute()
        flash('문의가 성공적으로 접수되었습니다.', 'success')
    
    return redirect(url_for('index'))

@app.route('/download-proposal')
def download_proposal():
    try:
        # 1. 'proposals' 버킷에 있는 파일 목록을 동적으로 가져옴 (하드코딩 제거)
        files = supabase.storage.from_('proposals').list()
        
        if not files:
            flash('다운로드할 제안서 파일이 없습니다.', 'warning')
            return redirect(url_for('index'))
        
        # 2. 버킷에 업로드된 첫 번째 파일의 이름을 동적으로 선택
        file_path = files[0]['name']
        
        # 3. Supabase Storage에서 파일 바이너리 데이터를 직접 다운로드
        file_data = supabase.storage.from_('proposals').download(file_path)
        
        # 4. Flask의 send_file을 사용하여 브라우저가 열지 않고 바로 다운로드하도록 강제함
        return send_file(
            io.BytesIO(file_data),
            as_attachment=True,          # 브라우저 미리보기가 아닌 강제 다운로드 실행
            download_name=file_path      # 다운로드될 때의 파일 이름 지정
        )
    except Exception as e:
        print("파일 다운로드 에러:", e)
        flash('제안서 파일을 다운로드하는 중 오류가 발생했습니다.', 'warning')
        return redirect(url_for('index'))


# --- [로그인 및 인증 라우팅] ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Supabase users 테이블에서 사용자 조회
        response = supabase.table('users').select("*").eq('username', username).execute()
        users = response.data
        
        # 평문 비교 대신 해시 검증 함수(check_password_hash) 사용
        if users and check_password_hash(users[0]['password_hash'], password):
            # 로그인 성공 시 세션 부여
            session['user_id'] = users[0]['id']
            session['username'] = users[0]['username']
            session['role'] = users[0]['role']
            session['company_name'] = users[0]['company_name']
            
            if session['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))
        else:
            flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# --- [대시보드 페이지 라우팅] ---

@app.route('/dashboard/user')
def user_dashboard():
    if 'user_id' not in session or session.get('role') != 'user':
        return redirect(url_for('login'))
    return render_template('user_dashboard.html', company_name=session.get('company_name'))

@app.route('/dashboard/admin')
@admin_required
def admin_dashboard():
    # 관리자 대시보드: 오프라인 가입 회원 목록과 고객 문의 내역 조회
    users_res = supabase.table('users').select("*").execute()
    inquiries_res = supabase.table('inquiries').select("*").order('created_at', desc=True).execute()
    
    users_data = users_res.data if users_res.data else []
    inquiries_data = inquiries_res.data if inquiries_res.data else []

    return render_template(
        'admin_dashboard.html', 
        users=users_res.data, 
        inquiries=inquiries_res.data
    )

@app.route('/dashboard/admin/add-user', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'GET':
        return render_template('add_user.html')
    
    # POST 요청 시 기존 회원 등록 로직 수행
    username = request.form.get('username')
    password = request.form.get('password')
    company_name = request.form.get('company_name')
    role = request.form.get('role', 'user')
    
    if username and password and company_name:
        password_hash = generate_password_hash(password)
        
        user_data = {
            "username": username,
            "password_hash": password_hash,
            "company_name": company_name,
            "role": role
        }
        
        # 동적으로 추가된 폼 필드(전화번호, 이메일 등) 자동 수집
        excluded_keys = ['username', 'password', 'company_name', 'role', 'csrf_token']
        for key, value in request.form.items():
            if key not in excluded_keys and value.strip():
                user_data[key] = value.strip()
                
        try:
            supabase.table('users').insert(user_data).execute()
            flash(f'성공적으로 [{company_name}] 회원이 등록되었습니다.', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            print("회원 등록 에러:", e)
            flash('회원 등록 중 오류가 발생했습니다. (아이디 중복 등 확인)', 'danger')
            
    return redirect(url_for('add_user'))

@app.route('/dashboard/admin/delete-user/<user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    try:
        # Supabase users 테이블에서 해당 ID의 회원 삭제
        supabase.table('users').delete().eq('id', user_id).execute()
        flash('회원이 성공적으로 삭제되었습니다.', 'success')
    except Exception as e:
        print("회원 삭제 에러:", e)
        flash('회원 삭제 중 오류가 발생했습니다.', 'danger')
        
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)