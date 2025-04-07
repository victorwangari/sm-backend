import jwt
import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get the JWT secret key
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'super-secret-key-change-in-production')

def decode_token(token):
    """Decode a JWT token and print its contents"""
    try:
        # Remove 'Bearer ' prefix if present
        if token.startswith('Bearer '):
            token = token[7:]
        
        # Decode the token
        decoded = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
        
        print("Token successfully decoded:")
        print(f"User ID: {decoded.get('sub')}")
        print(f"Expiration: {datetime.datetime.fromtimestamp(decoded.get('exp')).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Issued at: {datetime.datetime.fromtimestamp(decoded.get('iat')).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"All claims: {decoded}")
        
        return True, decoded
    except jwt.ExpiredSignatureError:
        print("Token has expired")
        return False, "Token has expired"
    except jwt.InvalidTokenError as e:
        print(f"Invalid token: {str(e)}")
        return False, f"Invalid token: {str(e)}"

def create_token(user_id):
    """Create a JWT token for testing"""
    payload = {
        'sub': user_id,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=1)
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm='HS256')
    print(f"Created token: {token}")
    return token

# Add this to app.py for debugging
@app.route('/api/debug-token', methods=['POST'])
def debug_token():
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({"error": "No token provided"}), 400
    
    # Remove 'Bearer ' prefix if present
    if token.startswith('Bearer '):
        token = token[7:]
    
    try:
        decoded = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        return jsonify({
            "valid": True,
            "decoded": decoded
        }), 200
    except Exception as e:
        return jsonify({
            "valid": False,
            "error": str(e)
        }), 200

# Usage example
if __name__ == "__main__":
    # Test with a sample token
    sample_token = "your_token_here"
    decode_token(sample_token)
    
    # Create a test token
    test_token = create_token(1)
    decode_token(test_token)

