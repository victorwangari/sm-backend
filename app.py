from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from datetime import timedelta
import os
from dotenv import load_dotenv
from models import db, User, Profile, Interest, UserInterest, Match, Message, Payment, Subscription
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import uuid
from daraja_api import initiate_payment, check_payment_status
import logging
import traceback

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Configure database - Using SQLite instead of PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///smash.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Configure JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'super-secret-key-change-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)
# Add these JWT configurations
app.config['JWT_TOKEN_LOCATION'] = ['headers']
app.config['JWT_HEADER_NAME'] = 'Authorization'
app.config['JWT_HEADER_TYPE'] = 'Bearer'
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db.init_app(app)
jwt = JWTManager(app)

# Add a JWT error handler
@jwt.invalid_token_loader
def invalid_token_callback(error_string):
    logger.error(f"Invalid JWT token: {error_string}")
    return jsonify({
        'error': 'Invalid token',
        'message': error_string
    }), 401

@jwt.unauthorized_loader
def unauthorized_callback(error_string):
    logger.error(f"Missing JWT token: {error_string}")
    return jsonify({
        'error': 'Authorization required',
        'message': error_string
    }), 401

# Create tables
@app.before_first_request
def create_tables():
    db.create_all()

# Helper functions
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_profile_image(file):
    if file and allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            # Generate unique filename
            unique_filename = f"{uuid.uuid4()}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(file_path)
            logger.info(f"Successfully saved image to {file_path}")
            return f"/uploads/{unique_filename}"
        except Exception as e:
            logger.error(f"Error saving file: {str(e)}")
            return None
    return None

# Routes
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    
    # Check if user already exists
    if User.query.filter_by(email=data['email']).first():
        return jsonify({"error": "Email already registered"}), 400
    
    # Create new user
    hashed_password = generate_password_hash(data['password'])
    new_user = User(
        name=data['name'],
        email=data['email'],
        password=hashed_password
    )
    
    db.session.add(new_user)
    db.session.commit()
    
    # Generate access token - Convert user_id to string
    access_token = create_access_token(identity=str(new_user.id))
    logger.debug(f"Created token for user ID: {new_user.id} (string: {str(new_user.id)})")
    
    return jsonify({
        "message": "User registered successfully",
        "user_id": new_user.id,
        "access_token": access_token
    }), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    
    user = User.query.filter_by(email=data['email']).first()
    
    if not user or not check_password_hash(user.password, data['password']):
        return jsonify({"error": "Invalid credentials"}), 401
    
    # Generate access token - Convert user_id to string
    access_token = create_access_token(identity=str(user.id))
    logger.debug(f"Created token for user ID: {user.id} (string: {str(user.id)})")
    
    # Check if user has a profile
    profile = Profile.query.filter_by(user_id=user.id).first()
    has_profile = profile is not None
    
    return jsonify({
        "message": "Login successful",
        "user_id": user.id,
        "name": user.name,
        "has_profile": has_profile,
        "access_token": access_token
    }), 200

@app.route('/api/profile', methods=['POST'])
@jwt_required()
def create_profile():
    # Get user_id from token - this will be a string
    user_id_str = get_jwt_identity()
    logger.debug(f"JWT identity (user_id): {user_id_str}, type: {type(user_id_str)}")
    
    # Convert to integer for database queries
    try:
        user_id = int(user_id_str)
    except ValueError:
        logger.error(f"Failed to convert user_id to integer: {user_id_str}")
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Check if profile already exists
    existing_profile = Profile.query.filter_by(user_id=user_id).first()
    if existing_profile:
        return jsonify({"error": "Profile already exists"}), 400
    
    try:
        # Log the incoming request data for debugging
        logger.debug(f"Received profile creation request from user {user_id}")
        logger.debug(f"Form data keys: {list(request.form.keys())}")
        logger.debug(f"Files keys: {list(request.files.keys()) if request.files else 'No files'}")
        
        # Handle form data and file upload
        data = request.form
        profile_image = None
        
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            logger.debug(f"Received file: {file.filename}, {file.content_type}, {file.content_length} bytes")
            if file and file.filename:
                profile_image = save_profile_image(file)
                logger.debug(f"Saved profile image to: {profile_image}")
        
        # Validate required fields
        required_fields = ['age', 'gender', 'location', 'bio', 'lookingFor']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            logger.error(f"Missing required fields: {missing_fields}")
            return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 422
        
        # Log all received fields for debugging
        for field in required_fields:
            if field in data:
                logger.debug(f"Field {field}: {data.get(field)}")
        
        # Create profile
        try:
            # Convert age to integer safely
            try:
                age = int(data.get('age', 18))
                logger.debug(f"Successfully converted age to integer: {age}")
            except ValueError as e:
                logger.error(f"Invalid age value: {data.get('age')}, error: {str(e)}")
                return jsonify({"error": f"Age must be a number, received: {data.get('age')}"}), 422
            
            new_profile = Profile(
                user_id=user_id,
                age=age,
                gender=data.get('gender'),
                location=data.get('location'),
                bio=data.get('bio'),
                looking_for=data.get('lookingFor'),  # Exact match with frontend camelCase
                profile_image=profile_image
            )
            
            logger.debug(f"Creating profile with: age={age}, gender={data.get('gender')}, location={data.get('location')}, bio={data.get('bio')}, lookingFor={data.get('lookingFor')}")
            
            db.session.add(new_profile)
            
            # Add interests
            if 'interests' in data:
                interests = data.getlist('interests')
                logger.debug(f"Processing interests: {interests}")
                for interest_name in interests:
                    # Check if interest exists, if not create it
                    interest = Interest.query.filter_by(name=interest_name).first()
                    if not interest:
                        interest = Interest(name=interest_name)
                        db.session.add(interest)
                        db.session.flush()
                    
                    # Add user interest
                    user_interest = UserInterest(user_id=user_id, interest_id=interest.id)
                    db.session.add(user_interest)
            
            db.session.commit()
            logger.info(f"Profile created successfully for user {user_id}")
            
            return jsonify({
                "message": "Profile created successfully",
                "profile_id": new_profile.id
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Database error creating profile: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({"error": f"Database error: {str(e)}"}), 500
            
    except Exception as e:
        logger.exception(f"Error creating profile: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": f"Error creating profile: {str(e)}"}), 500

@app.route('/api/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    # Get user_id from token - this will be a string
    user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        user_id = int(user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Get existing profile
    profile = Profile.query.filter_by(user_id=user_id).first()
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    
    # Handle form data and file upload
    data = request.form
    
    if 'profile_image' in request.files:
        profile_image = save_profile_image(request.files['profile_image'])
        if profile_image:
            profile.profile_image = profile_image
    
    # Update profile fields
    if 'age' in data:
        try:
            profile.age = int(data['age'])
        except ValueError:
            return jsonify({"error": "Age must be a number"}), 422
            
    if 'gender' in data:
        profile.gender = data['gender']
    if 'location' in data:
        profile.location = data['location']
    if 'bio' in data:
        profile.bio = data['bio']
    if 'lookingFor' in data:
        profile.looking_for = data['lookingFor']
    
    # Update interests
    if 'interests' in data:
        # Remove existing interests
        UserInterest.query.filter_by(user_id=user_id).delete()
        
        # Add new interests
        interests = data.getlist('interests')
        for interest_name in interests:
            # Check if interest exists, if not create it
            interest = Interest.query.filter_by(name=interest_name).first()
            if not interest:
                interest = Interest(name=interest_name)
                db.session.add(interest)
                db.session.flush()
            
            # Add user interest
            user_interest = UserInterest(user_id=user_id, interest_id=interest.id)
            db.session.add(user_interest)
    
    db.session.commit()
    
    return jsonify({
        "message": "Profile updated successfully"
    }), 200

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    # Get user_id from token - this will be a string
    user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        user_id = int(user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Get profile
    profile = Profile.query.filter_by(user_id=user_id).first()
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    
    # Get user
    user = User.query.get(user_id)
    
    # Get interests
    user_interests = UserInterest.query.filter_by(user_id=user_id).all()
    interests = []
    for user_interest in user_interests:
        interest = Interest.query.get(user_interest.interest_id)
        if interest:
            interests.append(interest.name)
    
    # Get subscription status
    subscription = Subscription.query.filter_by(user_id=user_id, is_active=True).first()
    
    # Get stats
    matches_count = Match.query.filter((Match.user1_id == user_id) | (Match.user2_id == user_id)).count()
    likes_received = Match.query.filter_by(user2_id=user_id, is_match=False).count()
    messages_count = Message.query.filter((Message.sender_id == user_id) | (Message.receiver_id == user_id)).count()
    
    return jsonify({
        "profile": {
            "id": profile.id,
            "name": user.name,
            "age": profile.age,
            "gender": profile.gender,
            "location": profile.location,
            "bio": profile.bio,
            "looking_for": profile.looking_for,
            "profile_image": profile.profile_image,
            "interests": interests,
            "created_at": profile.created_at.isoformat(),
            "premium_status": subscription.plan_type if subscription else None,
            "stats": {
                "matches": matches_count,
                "likes_received": likes_received,
                "messages": messages_count
            }
        }
    }), 200

@app.route('/api/users', methods=['GET'])
@jwt_required()
def get_users():
    # Get user_id from token - this will be a string
    user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        user_id = int(user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Get current user profile
    profile = Profile.query.filter_by(user_id=user_id).first()
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    
    # Get filter parameters
    min_age = request.args.get('min_age', 18, type=int)
    max_age = request.args.get('max_age', 80, type=int)
    interest = request.args.get('interest')
    
    # Query other users
    users_query = db.session.query(User, Profile).join(Profile).filter(User.id != user_id)
    
    # Apply filters
    users_query = users_query.filter(Profile.age >= min_age, Profile.age <= max_age)
    
    # Filter by interest if specified
    if interest and interest != 'all':
        interest_obj = Interest.query.filter_by(name=interest).first()
        if interest_obj:
            users_query = users_query.join(UserInterest, UserInterest.user_id == User.id).filter(UserInterest.interest_id == interest_obj.id)
    
    # Execute query
    users_result = users_query.all()
    
    # Format results
    users_list = []
    for user, profile in users_result:
        # Get interests for this user
        user_interests = UserInterest.query.filter_by(user_id=user.id).all()
        interests = []
        for user_interest in user_interests:
            interest = Interest.query.get(user_interest.interest_id)
            if interest:
                interests.append(interest.name)
        
        users_list.append({
            "id": user.id,
            "name": user.name,
            "age": profile.age,
            "location": profile.location,
            "bio": profile.bio,
            "profile_image": profile.profile_image,
            "interests": interests
        })
    
    return jsonify({
        "users": users_list
    }), 200

@app.route('/api/users/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    # Get user_id from token - this will be a string
    current_user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        current_user_id = int(current_user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Check if current user has premium subscription to view detailed profiles
    subscription = Subscription.query.filter_by(user_id=current_user_id, is_active=True).first()
    if not subscription:
        return jsonify({"error": "Premium subscription required to view detailed profiles"}), 403
    
    # Get user and profile
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    profile = Profile.query.filter_by(user_id=user_id).first()
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    
    # Get interests
    user_interests = UserInterest.query.filter_by(user_id=user_id).all()
    interests = []
    for user_interest in user_interests:
        interest = Interest.query.get(user_interest.interest_id)
        if interest:
            interests.append(interest.name)
    
    return jsonify({
        "user": {
            "id": user.id,
            "name": user.name,
            "age": profile.age,
            "gender": profile.gender,
            "location": profile.location,
            "bio": profile.bio,
            "looking_for": profile.looking_for,
            "profile_image": profile.profile_image,
            "interests": interests,
            "created_at": profile.created_at.isoformat()
        }
    }), 200

@app.route('/api/like/<int:user_id>', methods=['POST'])
@jwt_required()
def like_user(user_id):
    # Get user_id from token - this will be a string
    current_user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        current_user_id = int(current_user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Check if users exist
    if not User.query.get(current_user_id) or not User.query.get(user_id):
        return jsonify({"error": "User not found"}), 404
    
    # Check if already liked
    existing_match = Match.query.filter_by(user1_id=current_user_id, user2_id=user_id).first()
    if existing_match:
        return jsonify({"error": "Already liked this user"}), 400
    
    # Check if other user has already liked current user
    reverse_match = Match.query.filter_by(user1_id=user_id, user2_id=current_user_id).first()
    is_match = reverse_match is not None
    
    # Create new match/like
    new_match = Match(
        user1_id=current_user_id,
        user2_id=user_id,
        is_match=is_match
    )
    
    # If it's a match, update the reverse match
    if is_match:
        reverse_match.is_match = True
    
    db.session.add(new_match)
    db.session.commit()
    
    return jsonify({
        "message": "Like recorded successfully",
        "is_match": is_match
    }), 201

@app.route('/api/matches', methods=['GET'])
@jwt_required()
def get_matches():
    # Get user_id from token - this will be a string
    user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        user_id = int(user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Get all matches for the user
    matches = Match.query.filter(
        ((Match.user1_id == user_id) | (Match.user2_id == user_id)) & 
        (Match.is_match == True)
    ).all()
    
    # Format results
    matches_list = []
    for match in matches:
        # Get the other user in the match
        other_user_id = match.user2_id if match.user1_id == user_id else match.user1_id
        other_user = User.query.get(other_user_id)
        other_profile = Profile.query.filter_by(user_id=other_user_id).first()
        
        if other_user and other_profile:
            matches_list.append({
                "match_id": match.id,
                "user_id": other_user.id,
                "name": other_user.name,
                "age": other_profile.age,
                "location": other_profile.location,
                "profile_image": other_profile.profile_image,
                "matched_at": match.created_at.isoformat()
            })
    
    return jsonify({
        "matches": matches_list
    }), 200

@app.route('/api/messages/<int:user_id>', methods=['GET'])
@jwt_required()
def get_messages(user_id):
    # Get user_id from token - this will be a string
    current_user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        current_user_id = int(current_user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Check if users exist
    if not User.query.get(current_user_id) or not User.query.get(user_id):
        return jsonify({"error": "User not found"}), 404
    
    # Check if users are matched
    match = Match.query.filter(
        (((Match.user1_id == current_user_id) & (Match.user2_id == user_id)) | 
         ((Match.user1_id == user_id) & (Match.user2_id == current_user_id))) & 
        (Match.is_match == True)
    ).first()
    
    if not match:
        return jsonify({"error": "Users are not matched"}), 403
    
    # Get messages between users
    messages = Message.query.filter(
        ((Message.sender_id == current_user_id) & (Message.receiver_id == user_id)) | 
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user_id))
    ).order_by(Message.created_at).all()
    
    # Format results
    messages_list = []
    for message in messages:
        messages_list.append({
            "id": message.id,
            "sender_id": message.sender_id,
            "receiver_id": message.receiver_id,
            "content": message.content,
            "created_at": message.created_at.isoformat()
        })
    
    return jsonify({
        "messages": messages_list
    }), 200

@app.route('/api/messages/<int:user_id>', methods=['POST'])
@jwt_required()
def send_message(user_id):
    # Get user_id from token - this will be a string
    current_user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        current_user_id = int(current_user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    data = request.json
    
    # Check if users exist
    if not User.query.get(current_user_id) or not User.query.get(user_id):
        return jsonify({"error": "User not found"}), 404
    
    # Check if users are matched
    match = Match.query.filter(
        (((Match.user1_id == current_user_id) & (Match.user2_id == user_id)) | 
         ((Match.user1_id == user_id) & (Match.user2_id == current_user_id))) & 
        (Match.is_match == True)
    ).first()
    
    if not match:
        return jsonify({"error": "Users are not matched"}), 403
    
    # Create new message
    new_message = Message(
        sender_id=current_user_id,
        receiver_id=user_id,
        content=data['content']
    )
    
    db.session.add(new_message)
    db.session.commit()
    
    return jsonify({
        "message": "Message sent successfully",
        "message_id": new_message.id
    }), 201

@app.route('/api/subscription', methods=['GET'])
@jwt_required()
def get_subscription():
    # Get user_id from token - this will be a string
    user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        user_id = int(user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Get active subscription
    subscription = Subscription.query.filter_by(user_id=user_id, is_active=True).first()
    
    if not subscription:
        return jsonify({
            "has_subscription": False,
            "subscription": None
        }), 200
    
    return jsonify({
        "has_subscription": True,
        "subscription": {
            "id": subscription.id,
            "plan_type": subscription.plan_type,
            "start_date": subscription.start_date.isoformat(),
            "end_date": subscription.end_date.isoformat() if subscription.end_date else None,
            "is_active": subscription.is_active
        }
    }), 200

@app.route('/api/payment/initiate', methods=['POST'])
@jwt_required()
def initiate_payment_route():
    # Get user_id from token - this will be a string
    user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        user_id = int(user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    data = request.json
    
    # Get user
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Validate plan type
    plan_type = data.get('plan_type')
    if plan_type not in ['premium', 'platinum']:
        return jsonify({"error": "Invalid plan type"}), 400
    
    # Get amount based on plan type
    amount = 999 if plan_type == 'premium' else 1999  # $9.99 or $19.99
    
    # Get phone number
    phone_number = data.get('phone_number')
    if not phone_number:
        return jsonify({"error": "Phone number is required"}), 400
    
    # Initiate payment with Daraja API
    payment_response = initiate_payment(phone_number, amount, f"Smash Dating App {plan_type.capitalize()} Subscription")
    
    if 'error' in payment_response:
        return jsonify({"error": payment_response['error']}), 400
    
    # Create payment record
    new_payment = Payment(
        user_id=user_id,
        amount=amount,
        payment_method="M-Pesa",
        transaction_id=payment_response['transaction_id'],
        status="pending"
    )
    
    db.session.add(new_payment)
    db.session.commit()
    
    return jsonify({
        "message": "Payment initiated successfully",
        "payment_id": new_payment.id,
        "transaction_id": payment_response['transaction_id']
    }), 200

@app.route('/api/payment/verify/<transaction_id>', methods=['GET'])
@jwt_required()
def verify_payment(transaction_id):
    # Get user_id from token - this will be a string
    user_id_str = get_jwt_identity()
    
    # Convert to integer for database queries
    try:
        user_id = int(user_id_str)
    except ValueError:
        return jsonify({"error": "Invalid user ID"}), 400
    
    # Get payment
    payment = Payment.query.filter_by(transaction_id=transaction_id).first()
    if not payment:
        return jsonify({"error": "Payment not found"}), 404
    
    # Check if payment belongs to user
    if payment.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Check payment status with Daraja API
    payment_status = check_payment_status(transaction_id)
    
    if payment_status == "completed":
        # Update payment status
        payment.status = "completed"
        
        # Create or update subscription
        existing_subscription = Subscription.query.filter_by(user_id=user_id, is_active=True).first()
        
        if existing_subscription:
            # Update existing subscription
            existing_subscription.is_active = False
        
        # Determine plan type based on amount
        plan_type = "premium" if payment.amount == 999 else "platinum"
        
        # Create new subscription
        new_subscription = Subscription(
            user_id=user_id,
            payment_id=payment.id,
            plan_type=plan_type,
            is_active=True
        )
        
        db.session.add(new_subscription)
        db.session.commit()
        
        return jsonify({
            "message": "Payment verified successfully",
            "status": "completed",
            "subscription": {
                "id": new_subscription.id,
                "plan_type": new_subscription.plan_type,
                "start_date": new_subscription.start_date.isoformat(),
                "is_active": new_subscription.is_active
            }
        }), 200
    
    # Payment still pending or failed
    return jsonify({
        "message": "Payment status",
        "status": payment_status
    }), 200

@app.route('/api/interests', methods=['GET'])
def get_interests():
    interests = Interest.query.all()
    
    interests_list = [interest.name for interest in interests]
    
    return jsonify({
        "interests": interests_list
    }), 200

# Add a route to verify token
@app.route('/api/verify-token', methods=['GET'])
@jwt_required()
def verify_token():
    current_user_id = get_jwt_identity()
    
    # Log the token identity for debugging
    logger.debug(f"Token verification - identity: {current_user_id}, type: {type(current_user_id)}")
    
    # Convert to integer for database queries
    try:
        user_id = int(current_user_id)
    except ValueError:
        logger.error(f"Failed to convert user_id to integer: {current_user_id}")
        return jsonify({"error": "Invalid user ID"}), 400
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "message": "Token is valid",
        "user_id": user_id,
        "name": user.name
    }), 200

# Add a debug endpoint to check token
@app.route('/api/debug-token', methods=['POST'])
def debug_token():
    import jwt
    
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({"error": "No token provided"}), 400
    
    # Remove 'Bearer ' prefix if present
    if token.startswith('Bearer '):
        token = token[7:]
    
    try:
        decoded = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        logger.debug(f"Successfully decoded token: {decoded}")
        return jsonify({
            "valid": True,
            "decoded": decoded
        }), 200
    except Exception as e:
        logger.error(f"Error decoding token: {str(e)}")
        return jsonify({
            "valid": False,
            "error": str(e)
        }), 200

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def server_error(error):
    logger.error(f"Server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(422)
def unprocessable_entity(error):
    logger.error(f"Validation error: {error}")
    return jsonify({"error": "Validation error. Please check your input data."}), 422

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

