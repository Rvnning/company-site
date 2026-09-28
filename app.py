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

# 4. 로그인 여부를 확인하는 데코레이터
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('로그인이 필요합니다.', 'danger')
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

@app.route('/dashboard/admin/update-inquiry-status/<int:inquiry_id>', methods=['POST'])
@admin_required
def update_inquiry_status(inquiry_id):
    new_status = request.form.get('status')
    
    if new_status:
        try:
            # Supabase inquiries 테이블의 status 업데이트
            supabase.table('inquiries').update({"status": new_status}).eq('id', inquiry_id).execute()
            flash('문의 처리 상태가 변경되었습니다.', 'success')
        except Exception as e:
            print("문의 상태 변경 에러:", e)
            flash('상태 변경 중 오류가 발생했습니다.', 'danger')
            
    return redirect(url_for('admin_dashboard'))

import io

# --- [관리자: 제안서 파일 업로드 라우트] ---
@app.route('/dashboard/admin/upload-proposal', methods=['POST'])
@admin_required
def upload_proposal():
    file = request.files.get('proposal_file')
    
    if file and file.filename:
        try:
            file_bytes = file.read()
            file_name = "cierra_proposal.pdf"  # 항상 최신 파일명으로 고정하여 덮어쓰기
            
            # Supabase Storage의 proposals 버킷에 업로드 (upsert=true로 기존 파일 덮어쓰기)
            supabase.storage.from_('proposals').upload(
                path=file_name,
                file=file_bytes,
                file_options={"upsert": "true", "content-type": "application/pdf"}
            )
            
            flash('회사 소개서가 성공적으로 업로드 및 갱신되었습니다.', 'success')
        except Exception as e:
            print("제안서 업로드 에러:", e)
            flash('파일 업로드 중 오류가 발생했습니다.', 'danger')
    else:
        flash('업로드할 PDF 파일을 선택해 주세요.', 'warning')
        
    return redirect(url_for('admin_dashboard'))

# --- [사용자: 제안서 다운로드 라우트] ---
@app.route('/download-proposal')
def download_proposal():
    try:
        # Supabase Storage에서 제안서 파일 바이트 데이터 가져오기
        file_data = supabase.storage.from_('proposals').download('cierra_proposal.pdf')
        
        return send_file(
            io.BytesIO(file_data),
            mimetype='application/pdf',
            as_attachment=True,
            download_name='Cierra_Energy_Company_Profile.pdf'
        )
    except Exception as e:
        print("제안서 다운로드 에러:", e)
        flash('등록된 회사 소개서 파일이 없거나 다운로드 중 오류가 발생했습니다.', 'warning')
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

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'GET':
        return render_template('reset_password.html')
    
    username = request.form.get('username')
    company_name = request.form.get('company_name')
    new_password = request.form.get('new_password')
    
    if username and company_name and new_password:
        # 1. 아이디와 회사명이 일치하는 사용자가 있는지 확인
        response = supabase.table('users').select("*").eq('username', username).eq('company_name', company_name).execute()
        
        if response.data:
            # 2. 새 비밀번호 해시화
            new_password_hash = generate_password_hash(new_password)
            
            # 3. Supabase 비밀번호 업데이트
            supabase.table('users').update({"password_hash": new_password_hash}).eq('username', username).execute()
            
            flash('비밀번호가 성공적으로 변경되었습니다. 새 비밀번호로 로그인해 주세요.', 'success')
            return redirect(url_for('login'))
        else:
            flash('입력하신 정보와 일치하는 회원을 찾을 수 없습니다.', 'danger')
            
    return render_template('reset_password.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# --- [대시보드 페이지 라우팅] ---

# --- [일반 회원 마이페이지 라우트] ---
@app.route('/dashboard/user', methods=['GET', 'POST'])
@login_required
def user_dashboard():
    user_id = session.get('user_id')
    
    if request.method == 'POST':
        company_name = request.form.get('company_name')
        phone = request.form.get('phone', '')
        email = request.form.get('email', '')
        
        update_data = {
            "company_name": company_name,
            "phone": phone,
            "email": email
        }
        
        try:
            # Supabase users 테이블에서 현재 로그인한 유저의 정보 업데이트
            supabase.table('users').update(update_data).eq('id', user_id).execute()
            
            # 세션에 저장된 회사명 캐시도 함께 갱신
            session['company_name'] = company_name
            flash('회원 정보가 성공적으로 수정되었습니다.', 'success')
        except Exception as e:
            print("회원 정보 수정 에러:", e)
            flash('정보 수정 중 오류가 발생했습니다.', 'danger')
            
        return redirect(url_for('user_dashboard'))
    
    # GET 요청 시 현재 회원의 최신 정보를 Supabase에서 조회
    response = supabase.table('users').select("*").eq('id', user_id).execute()
    user_info = response.data[0] if response.data else {}
    
    return render_template('user_dashboard.html', user=user_info)

@app.route('/dashboard/admin')
@admin_required
def admin_dashboard():
    # 관리자 대시보드: 오프라인 가입 회원 목록과 고객 문의 내역 조회
    users_res = supabase.table('users').select("*").execute()
    inquiries_res = supabase.table('inquiries').select("*").order('created_at', desc=True).execute()
    notices_res = supabase.table('notices').select("*").order('created_at', desc=True).execute()

    users_data = users_res.data if users_res.data else []
    inquiries_data = inquiries_res.data if inquiries_res.data else []
    notices_data = notices_res.data if notices_res.data else []
    
    return render_template(
        'admin_dashboard.html', 
        users=users_res.data, 
        inquiries=inquiries_res.data,
        notices=notices_data
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

# --- [사용자: 공지사항 목록 및 상세 보기] ---
@app.route('/notices')
def notice_list():
    response = supabase.table('notices').select("*").order('created_at', desc=True).execute()
    notices = response.data if response.data else []
    return render_template('notice_list.html', notices=notices)

@app.route('/notices/<int:notice_id>')
def notice_detail(notice_id):
    response = supabase.table('notices').select("*").eq('id', notice_id).execute()
    if not response.data:
        flash('존재하지 않거나 삭제된 게시글입니다.', 'warning')
        return redirect(url_for('notice_list'))
    
    notice = response.data[0]

    if notice.get('link_url'):
        return redirect(notice['link_url'])

    return render_template('notice_detail.html', notice=notice)

    try:
        supabase.table('notices').insert({
            "title": title,
            "category": category,
            "content": content,
            "link_url": link_url if link_url else None
        }).execute()
        flash('공지사항이 성공적으로 등록되었습니다.', 'success')
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        print("공지사항 등록 에러:", e)
        flash('등록 중 오류가 발생했습니다.', 'danger')
            
    return redirect(url_for('add_notice'))

# --- [관리자: 공지사항 삭제] ---
@app.route('/dashboard/admin/notices/delete/<int:notice_id>', methods=['POST'])
@admin_required
def delete_notice(notice_id):
    try:
        supabase.table('notices').delete().eq('id', notice_id).execute()
        flash('게시글이 삭제되었습니다.', 'success')
    except Exception as e:
        print("공지사항 삭제 에러:", e)
        flash('삭제 중 오류가 발생했습니다.', 'danger')
        
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)