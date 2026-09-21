import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash
from supabase import create_client, Client
from dotenv import load_dotenv
from werkzeug.security import check_password_hash
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
    # Supabase Storage(proposals 버킷)에 있는 파일 다운로드 링크로 리다이렉트
    # (또는 static/uploads 폴더에 파일을 넣고 전송할 수도 있습니다.)
    try:
        # Supabase Storage Public URL 가져오기 예시 (파일명: company_intro.pdf 기준)
        file_path = "company_intro.pdf"
        public_url = supabase.storage.from_('proposals').get_public_url(file_path)
        return redirect(public_url)
    except Exception as e:
        flash('제안서 파일을 찾을 수 없습니다.', 'warning')
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
        print("조회된 유저 데이터:", users)
        
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
    
    return render_template(
        'admin_dashboard.html', 
        users=users_res.data, 
        inquiries=inquiries_res.data
    )

if __name__ == '__main__':
    app.run(debug=True)