"""
New Hire Onboarding Form - Flask Backend
FirstLine Schools
"""

import os
import json
import uuid
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, send_file, session, redirect, url_for
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from google.cloud import bigquery
from authlib.integrations.flask_client import OAuth

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
CORS(app)

# Configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
PROJECT_ID = os.environ.get('GOOGLE_CLOUD_PROJECT', 'talent-demo-482004')
DATASET_ID = 'onboarding_form'
TABLE_ID = 'submissions'

# Email Configuration
SMTP_EMAIL = os.environ.get('SMTP_EMAIL', 'talent@firstlineschools.org')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
TALENT_TEAM_EMAIL = 'talent@firstlineschools.org'
HR_EMAIL = 'hr@firstlineschools.org'
CPO_EMAIL = 'sshirey@firstlineschools.org'

# Role-based admin permissions
ADMIN_ROLES = {
    'sshirey@firstlineschools.org': {
        'role': 'super_admin',
        'title': 'Chief People Officer',
        'can_edit': True,
        'can_delete': True,
    },
    'brichardson@firstlineschools.org': {
        'role': 'hr',
        'title': 'Chief HR Officer',
        'can_edit': True,
        'can_delete': False,
    },
    'mtoussaint@firstlineschools.org': {
        'role': 'hr',
        'title': 'HR Manager',
        'can_edit': True,
        'can_delete': False,
    },
    'csmith@firstlineschools.org': {
        'role': 'viewer',
        'title': 'Talent',
        'can_edit': False,
        'can_delete': False,
    },
    'aleibfritz@firstlineschools.org': {
        'role': 'viewer',
        'title': 'Payroll Manager',
        'can_edit': False,
        'can_delete': False,
    },
}

ADMIN_USERS = list(ADMIN_ROLES.keys())


def get_user_permissions(email):
    """Get the permissions for an admin user."""
    email = (email or '').lower()
    role_info = ADMIN_ROLES.get(email)
    if not role_info:
        return None
    return {
        'role': role_info['role'],
        'title': role_info['title'],
        'can_edit': role_info['can_edit'],
        'can_delete': role_info['can_delete'],
        'can_archive': role_info['role'] != 'viewer',
        'is_viewer': role_info['role'] == 'viewer',
    }


# BigQuery client
bq_client = bigquery.Client(project=PROJECT_ID)


def ensure_is_archived_column():
    """One-time migration: add is_archived column if it doesn't exist."""
    try:
        full_table = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
        table_ref = bq_client.get_table(full_table)
        existing_fields = [f.name for f in table_ref.schema]
        if 'is_archived' not in existing_fields:
            bq_client.query(f"ALTER TABLE `{full_table}` ADD COLUMN is_archived BOOL").result()
            bq_client.query(f"ALTER TABLE `{full_table}` ALTER COLUMN is_archived SET DEFAULT FALSE").result()
            bq_client.query(f"UPDATE `{full_table}` SET is_archived = FALSE WHERE TRUE").result()
            logger.info("Added is_archived column to submissions table")
    except Exception as e:
        logger.error(f"Migration error (is_archived): {e}")


ensure_is_archived_column()

# OAuth setup
oauth = OAuth(app)
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    google = oauth.register(
        name='google',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )
else:
    google = None


# ============ Email Functions ============

def send_email(to_email, subject, html_body, cc_emails=None):
    """Send an email using Gmail SMTP."""
    if not SMTP_PASSWORD:
        logger.warning("SMTP_PASSWORD not configured, skipping email")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"FirstLine Schools Talent <{SMTP_EMAIL}>"
        msg['To'] = to_email
        if cc_emails:
            msg['Cc'] = ', '.join(cc_emails)

        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            recipients = [to_email] + (cc_emails or [])
            server.sendmail(SMTP_EMAIL, recipients, msg.as_string())

        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_submission_confirmation(sub):
    """Send welcome confirmation to new hire after they submit the form."""
    subject = f"Welcome to FirstLine Schools, {sub['preferred_name']}!"
    html_body = f"""
    <div style="font-family: 'Open Sans', Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #002f60, #094aad); padding: 30px; text-align: center;">
            <h1 style="color: white; margin: 0; font-size: 28px;">Welcome to the Team!</h1>
            <p style="color: #f8d47a; margin: 10px 0 0 0; font-size: 16px;">We're so excited to have you!</p>
        </div>
        <div style="padding: 30px; background-color: #f8f9fa;">
            <h2 style="color: #002f60;">Hi {sub['preferred_name']},</h2>
            <p>Thank you for completing your onboarding form! We've received your information and our HR team is preparing everything for your arrival.</p>

            <div style="background-color: white; border-radius: 8px; padding: 20px; margin: 20px 0;">
                <p style="margin: 5px 0;"><strong>Confirmation ID:</strong> {sub['submission_id']}</p>
                <p style="margin: 5px 0;"><strong>School/Location:</strong> {sub['school_location']}</p>
            </div>

            <p><strong>What happens next?</strong></p>
            <ul>
                <li>Our team will stay in touch with you to support your onboarding</li>
                <li>You'll receive information about benefits enrollment</li>
                <li>We'll have your welcome kit ready for you</li>
                <li>Your school leader will be in touch to welcome you to your team</li>
            </ul>

            <div style="background-color: #e8f4f8; border-radius: 8px; padding: 20px; margin: 20px 0; text-align: center;">
                <p style="color: #002f60; font-size: 1.1em; margin: 0;"><strong>We can't wait to see the impact you'll make!</strong></p>
            </div>

            <p style="color: #666; font-size: 0.9em; margin-top: 30px;">Questions? Contact <a href="mailto:hr@firstlineschools.org">hr@firstlineschools.org</a> or <a href="mailto:talent@firstlineschools.org">talent@firstlineschools.org</a></p>
        </div>
        <div style="background-color: #002f60; padding: 15px; text-align: center;">
            <p style="color: white; margin: 0; font-size: 0.9em;">FirstLine Schools - Education For Life</p>
        </div>
    </div>
    """
    send_email(sub['email'], subject, html_body)


def send_new_submission_alert(sub):
    """Send alert to HR team when a new onboarding form is submitted."""
    subject = f"New Onboarding Form: {sub['first_name']} {sub['last_name']} - {sub['school_location']}"
    html_body = f"""
    <div style="font-family: 'Open Sans', Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background-color: #002f60; padding: 20px; text-align: center;">
            <h1 style="color: white; margin: 0;">New Onboarding Submission</h1>
        </div>
        <div style="padding: 30px; background-color: #f8f9fa;">
            <h2 style="color: #e47727;">New hire form received!</h2>

            <div style="background-color: white; border-radius: 8px; padding: 20px; margin: 20px 0;">
                <h3 style="color: #002f60; margin-top: 0;">New Hire Details</h3>
                <p style="margin: 5px 0;"><strong>Name:</strong> {sub['first_name']} {sub['last_name']}</p>
                <p style="margin: 5px 0;"><strong>Preferred Name:</strong> {sub['preferred_name']}</p>
                <p style="margin: 5px 0;"><strong>Email:</strong> {sub['email']}</p>
                <p style="margin: 5px 0;"><strong>Phone:</strong> {sub['phone']}</p>
                <p style="margin: 5px 0;"><strong>Address:</strong> {sub['physical_address']}</p>
                <p style="margin: 5px 0;"><strong>School/Location:</strong> {sub['school_location']}</p>
                <p style="margin: 5px 0;"><strong>T-Shirt Size:</strong> {sub['tshirt_size']}</p>
            </div>

            <div style="background-color: white; border-radius: 8px; padding: 20px; margin: 20px 0;">
                <h3 style="color: #002f60; margin-top: 0;">Dietary & Health</h3>
                <p style="margin: 5px 0;"><strong>Dietary Needs:</strong> {sub['dietary_needs']}</p>
                <p style="margin: 5px 0;"><strong>Food Allergies:</strong> {sub['food_allergies']}</p>
                <p style="margin: 5px 0;"><strong>ADA Accommodation:</strong> {sub['ada_accommodation']}</p>
            </div>

            <div style="background-color: white; border-radius: 8px; padding: 20px; margin: 20px 0;">
                <h3 style="color: #002f60; margin-top: 0;">Certifications</h3>
                <p style="margin: 5px 0;"><strong>Science of Reading (K-3):</strong> {sub['reading_certification']}</p>
                <p style="margin: 5px 0;"><strong>Numeracy/Act 108 (4-8):</strong> {sub['numeracy_coursework']}</p>
            </div>

            <div style="background-color: #fff3cd; border-radius: 8px; padding: 15px; margin: 20px 0;">
                <p style="margin: 0;"><strong>Submission ID:</strong> {sub['submission_id']}</p>
            </div>
        </div>
    </div>
    """
    send_email(HR_EMAIL, subject, html_body, cc_emails=[TALENT_TEAM_EMAIL, CPO_EMAIL])


# ============ BigQuery Functions ============

def get_full_table_id():
    return f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"


def row_to_dict(row):
    """Convert a BigQuery row to a dictionary."""
    return {
        'submission_id': row.submission_id,
        'submitted_at': row.submitted_at.isoformat() if row.submitted_at else '',
        'email': row.email or '',
        'first_name': row.first_name or '',
        'last_name': row.last_name or '',
        'preferred_name': row.preferred_name or '',
        'school_location': row.school_location or '',
        'phone': getattr(row, 'phone', '') or '',
        'physical_address': getattr(row, 'physical_address', '') or '',
        'tshirt_size': row.tshirt_size or '',
        'dietary_needs': row.dietary_needs or '',
        'food_allergies': row.food_allergies or '',
        'reading_certification': row.reading_certification or '',
        'numeracy_coursework': row.numeracy_coursework or '',
        'ada_accommodation': row.ada_accommodation or '',
        'onboarding_status': row.onboarding_status or '',
        'start_date': row.start_date.isoformat() if row.start_date else '',
        'position_title': row.position_title or '',
        'badge_printed': row.badge_printed or '',
        'equipment_issued': row.equipment_issued or '',
        'orientation_complete': row.orientation_complete or '',
        'admin_notes': row.admin_notes or '',
        'updated_at': row.updated_at.isoformat() if row.updated_at else '',
        'updated_by': row.updated_by or '',
        'is_archived': bool(getattr(row, 'is_archived', False) or False),
    }


def read_all_submissions():
    try:
        query = f"SELECT * FROM `{get_full_table_id()}` ORDER BY submitted_at DESC"
        results = bq_client.query(query).result()
        return [row_to_dict(row) for row in results]
    except Exception as e:
        logger.error(f"Error reading submissions: {e}")
        return []


def get_submission_by_id(submission_id):
    try:
        query = f"SELECT * FROM `{get_full_table_id()}` WHERE submission_id = @submission_id"
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("submission_id", "STRING", submission_id)]
        )
        results = bq_client.query(query, job_config=job_config).result()
        for row in results:
            return row_to_dict(row)
        return None
    except Exception as e:
        logger.error(f"Error getting submission: {e}")
        return None


def append_submission(data):
    """Insert a new submission into BigQuery."""
    try:
        query = f"""
        INSERT INTO `{get_full_table_id()}` (
            submission_id, submitted_at, email, first_name, last_name, preferred_name,
            school_location, tshirt_size, dietary_needs, food_allergies,
            reading_certification, numeracy_coursework, ada_accommodation,
            onboarding_status, start_date, position_title,
            badge_printed, equipment_issued, orientation_complete,
            admin_notes, updated_at, updated_by, is_archived
        ) VALUES (
            @submission_id, @submitted_at, @email, @first_name, @last_name, @preferred_name,
            @school_location, @tshirt_size, @dietary_needs, @food_allergies,
            @reading_certification, @numeracy_coursework, @ada_accommodation,
            @onboarding_status, @start_date, @position_title,
            @badge_printed, @equipment_issued, @orientation_complete,
            @admin_notes, @updated_at, @updated_by, @is_archived
        )
        """

        submitted_at = datetime.fromisoformat(data['submitted_at']) if data.get('submitted_at') else datetime.now()
        updated_at = datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else datetime.now()

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("submission_id", "STRING", data.get('submission_id', '')),
                bigquery.ScalarQueryParameter("submitted_at", "TIMESTAMP", submitted_at),
                bigquery.ScalarQueryParameter("email", "STRING", data.get('email', '')),
                bigquery.ScalarQueryParameter("first_name", "STRING", data.get('first_name', '')),
                bigquery.ScalarQueryParameter("last_name", "STRING", data.get('last_name', '')),
                bigquery.ScalarQueryParameter("preferred_name", "STRING", data.get('preferred_name', '')),
                bigquery.ScalarQueryParameter("school_location", "STRING", data.get('school_location', '')),
                bigquery.ScalarQueryParameter("tshirt_size", "STRING", data.get('tshirt_size', '')),
                bigquery.ScalarQueryParameter("dietary_needs", "STRING", data.get('dietary_needs', '')),
                bigquery.ScalarQueryParameter("food_allergies", "STRING", data.get('food_allergies', '')),
                bigquery.ScalarQueryParameter("reading_certification", "STRING", data.get('reading_certification', 'N/A')),
                bigquery.ScalarQueryParameter("numeracy_coursework", "STRING", data.get('numeracy_coursework', 'N/A')),
                bigquery.ScalarQueryParameter("ada_accommodation", "STRING", data.get('ada_accommodation', 'None')),
                bigquery.ScalarQueryParameter("onboarding_status", "STRING", data.get('onboarding_status', 'Not Started')),
                bigquery.ScalarQueryParameter("start_date", "DATE", None),
                bigquery.ScalarQueryParameter("position_title", "STRING", data.get('position_title', '')),
                bigquery.ScalarQueryParameter("badge_printed", "STRING", data.get('badge_printed', 'No')),
                bigquery.ScalarQueryParameter("equipment_issued", "STRING", data.get('equipment_issued', 'No')),
                bigquery.ScalarQueryParameter("orientation_complete", "STRING", data.get('orientation_complete', 'No')),
                bigquery.ScalarQueryParameter("admin_notes", "STRING", data.get('admin_notes', '')),
                bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", updated_at),
                bigquery.ScalarQueryParameter("updated_by", "STRING", data.get('updated_by', '')),
                bigquery.ScalarQueryParameter("is_archived", "BOOL", False),
            ]
        )

        bq_client.query(query, job_config=job_config).result()
        return True
    except Exception as e:
        logger.error(f"Error appending submission: {e}")
        return False


def update_submission(submission_id, updates):
    """Update a submission in BigQuery."""
    try:
        set_clauses = []
        params = [bigquery.ScalarQueryParameter("submission_id", "STRING", submission_id)]

        for field, value in updates.items():
            param_name = f"param_{field}"

            if field == 'start_date':
                if value:
                    set_clauses.append(f"{field} = @{param_name}")
                    params.append(bigquery.ScalarQueryParameter(param_name, "DATE", value))
                else:
                    set_clauses.append(f"{field} = NULL")
            elif field in ['updated_at', 'submitted_at']:
                set_clauses.append(f"{field} = @{param_name}")
                params.append(bigquery.ScalarQueryParameter(param_name, "TIMESTAMP", datetime.fromisoformat(value)))
            elif field == 'is_archived':
                set_clauses.append(f"{field} = @{param_name}")
                params.append(bigquery.ScalarQueryParameter(param_name, "BOOL", bool(value)))
            else:
                set_clauses.append(f"{field} = @{param_name}")
                params.append(bigquery.ScalarQueryParameter(param_name, "STRING", str(value)))

        if not set_clauses:
            return True

        query = f"""
        UPDATE `{get_full_table_id()}`
        SET {', '.join(set_clauses)}
        WHERE submission_id = @submission_id
        """

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        bq_client.query(query, job_config=job_config).result()
        return True
    except Exception as e:
        logger.error(f"Error updating submission: {e}")
        return False


def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user')
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        if user.get('email', '').lower() not in [e.lower() for e in ADMIN_USERS]:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


# ============ Public Routes ============

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.getcwd()


@app.route('/')
def index():
    return send_file(os.path.join(SCRIPT_DIR, 'index.html'))


@app.route('/api/submissions', methods=['POST'])
def submit_form():
    """Submit a new onboarding form."""
    try:
        data = request.json

        required_fields = ['email', 'first_name', 'last_name', 'preferred_name', 'school_location',
                          'phone', 'physical_address',
                          'tshirt_size', 'dietary_needs', 'food_allergies',
                          'reading_certification', 'numeracy_coursework', 'ada_accommodation']

        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400

        submission_id = str(uuid.uuid4())[:8].upper()
        submitted_at = datetime.now().isoformat()

        sub = {
            'submission_id': submission_id,
            'submitted_at': submitted_at,
            'email': data.get('email', '').lower(),
            'first_name': data.get('first_name', ''),
            'last_name': data.get('last_name', ''),
            'preferred_name': data.get('preferred_name', ''),
            'school_location': data.get('school_location', ''),
            'phone': data.get('phone', ''),
            'physical_address': data.get('physical_address', ''),
            'tshirt_size': data.get('tshirt_size', ''),
            'dietary_needs': data.get('dietary_needs', ''),
            'food_allergies': data.get('food_allergies', ''),
            'reading_certification': data.get('reading_certification', 'N/A'),
            'numeracy_coursework': data.get('numeracy_coursework', 'N/A'),
            'ada_accommodation': data.get('ada_accommodation', 'None'),
            'onboarding_status': 'Not Started',
            'position_title': '',
            'badge_printed': 'No',
            'equipment_issued': 'No',
            'orientation_complete': 'No',
            'admin_notes': '',
            'updated_at': submitted_at,
            'updated_by': 'System',
        }

        if append_submission(sub):
            send_submission_confirmation(sub)
            send_new_submission_alert(sub)

            return jsonify({
                'success': True,
                'submission_id': submission_id,
                'preferred_name': sub['preferred_name'],
            })
        else:
            return jsonify({'error': 'Failed to save submission'}), 500

    except Exception as e:
        logger.error(f"Error submitting form: {e}")
        return jsonify({'error': 'Server error'}), 500


@app.route('/api/submissions/lookup', methods=['GET'])
def lookup_submissions():
    """Look up submissions by email."""
    email = request.args.get('email', '').lower().strip()
    if not email:
        return jsonify({'error': 'Email required'}), 400

    all_subs = read_all_submissions()
    user_subs = [s for s in all_subs if s.get('email', '').lower() == email]

    # Remove admin fields
    for s in user_subs:
        s.pop('admin_notes', None)

    return jsonify({
        'submissions': user_subs,
        'total': len(user_subs),
    })


# ============ Auth Routes ============

@app.route('/login')
def login():
    if not google:
        return jsonify({'error': 'OAuth not configured'}), 500
    redirect_uri = url_for('auth_callback', _external=True)
    # Force new-format Cloud Run URL so OAuth callback matches registered URI
    redirect_uri = redirect_uri.replace('daem7b6ydq-uc.a.run.app', '965913991496.us-central1.run.app')
    return google.authorize_redirect(redirect_uri)


@app.route('/auth/callback')
def auth_callback():
    if not google:
        return jsonify({'error': 'OAuth not configured'}), 500
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if user_info:
            session['user'] = {
                'email': user_info.get('email'),
                'name': user_info.get('name'),
                'picture': user_info.get('picture')
            }
        return redirect('/?admin=true')
    except Exception as e:
        logger.error(f"OAuth error: {e}")
        return redirect('/?error=auth_failed')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


@app.route('/api/auth/status')
def auth_status():
    user = session.get('user')
    if user:
        email = user.get('email', '').lower()
        is_admin = email in [e.lower() for e in ADMIN_USERS]
        permissions = get_user_permissions(email) if is_admin else None
        return jsonify({
            'authenticated': True,
            'is_admin': is_admin,
            'user': user,
            'permissions': permissions,
        })
    return jsonify({'authenticated': False, 'is_admin': False, 'permissions': None})


# ============ Admin Routes ============

@app.route('/api/admin/submissions', methods=['GET'])
@require_admin
def get_all_submissions():
    subs = read_all_submissions()
    return jsonify({'submissions': subs})


@app.route('/api/admin/submissions/<submission_id>', methods=['PATCH'])
@require_admin
def update_submission_status(submission_id):
    """Update a submission (role-based permissions enforced)."""
    try:
        data = request.json
        user = session.get('user', {})
        email = user.get('email', '').lower()
        perms = get_user_permissions(email)

        if not perms or not perms['can_edit']:
            return jsonify({'error': 'You do not have permission to edit submissions'}), 403

        updates = {}

        # Admin-editable fields
        for field in ['onboarding_status', 'position_title', 'badge_printed',
                      'equipment_issued', 'orientation_complete', 'admin_notes']:
            if field in data:
                updates[field] = data[field]

        if 'start_date' in data:
            updates['start_date'] = data['start_date']

        updates['updated_at'] = datetime.now().isoformat()
        updates['updated_by'] = user.get('email', 'Unknown')

        if update_submission(submission_id, updates):
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Submission not found'}), 404

    except Exception as e:
        logger.error(f"Error updating submission: {e}")
        return jsonify({'error': 'Server error'}), 500


@app.route('/api/admin/submissions/<submission_id>', methods=['DELETE'])
@require_admin
def delete_submission(submission_id):
    try:
        email = session.get('user', {}).get('email', '').lower()
        perms = get_user_permissions(email)
        if not perms or not perms['can_delete']:
            return jsonify({'error': 'Only super admins can delete submissions'}), 403

        query = f"DELETE FROM `{get_full_table_id()}` WHERE submission_id = @submission_id"
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("submission_id", "STRING", submission_id)]
        )
        bq_client.query(query, job_config=job_config).result()
        logger.info(f"Deleted submission {submission_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error deleting submission: {e}")
        return jsonify({'error': 'Server error'}), 500


@app.route('/api/admin/submissions/<submission_id>/archive', methods=['PATCH'])
@require_admin
def archive_submission(submission_id):
    try:
        email = session.get('user', {}).get('email', '').lower()
        perms = get_user_permissions(email)
        if not perms or not perms['can_archive']:
            return jsonify({'error': 'You do not have permission to archive'}), 403

        query = f"UPDATE `{get_full_table_id()}` SET is_archived = TRUE WHERE submission_id = @submission_id"
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("submission_id", "STRING", submission_id)]
        )
        bq_client.query(query, job_config=job_config).result()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error archiving submission: {e}")
        return jsonify({'error': 'Server error'}), 500


@app.route('/api/admin/submissions/<submission_id>/unarchive', methods=['PATCH'])
@require_admin
def unarchive_submission(submission_id):
    try:
        query = f"UPDATE `{get_full_table_id()}` SET is_archived = FALSE WHERE submission_id = @submission_id"
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("submission_id", "STRING", submission_id)]
        )
        bq_client.query(query, job_config=job_config).result()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error unarchiving submission: {e}")
        return jsonify({'error': 'Server error'}), 500


@app.route('/api/admin/stats', methods=['GET'])
@require_admin
def get_stats():
    all_subs = read_all_submissions()
    subs = [s for s in all_subs if not s.get('is_archived')]

    total = len(subs)
    not_started = len([s for s in subs if s.get('onboarding_status') == 'Not Started'])
    in_progress = len([s for s in subs if s.get('onboarding_status') == 'In Progress'])
    complete = len([s for s in subs if s.get('onboarding_status') == 'Complete'])
    needs_accommodation = len([s for s in subs if s.get('ada_accommodation', 'None') != 'None'])

    return jsonify({
        'total': total,
        'not_started': not_started,
        'in_progress': in_progress,
        'complete': complete,
        'needs_accommodation': needs_accommodation,
    })


# ============ Health Check ============

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
