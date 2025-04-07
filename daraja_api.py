import requests
import base64
import os
from datetime import datetime
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Safaricom Daraja API credentials
CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY')
CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET')
BUSINESS_SHORT_CODE = os.getenv('MPESA_BUSINESS_SHORT_CODE')
PASSKEY = os.getenv('MPESA_PASSKEY')
CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL')
TRANSACTION_TYPE = "CustomerPayBillOnline"
TRANSACTION_DESCRIPTION = "Payment for Smash Dating App subscription"
ACCOUNT_REFERENCE = "Smash"
TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"

def generate_access_token():
    """Generate OAuth access token for M-Pesa API"""
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    
    # Encode consumer key and secret
    auth_string = f"{CONSUMER_KEY}:{CONSUMER_SECRET}"
    auth_bytes = auth_string.encode("ascii")
    base64_bytes = base64.b64encode(auth_bytes)
    base64_string = base64_bytes.decode("ascii")
    
    headers = {
        "Authorization": f"Basic {base64_string}"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response_data = response.json()
        
        if 'access_token' in response_data:
            return response_data['access_token']
        else:
            return None
    except Exception as e:
        print(f"Error generating access token: {str(e)}")
        return None

def generate_password():
    """Generate password for M-Pesa API"""
    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    password_string = f"{BUSINESS_SHORT_CODE}{PASSKEY}{timestamp}"
    password_bytes = password_string.encode("ascii")
    base64_bytes = base64.b64encode(password_bytes)
    base64_string = base64_bytes.decode("ascii")
    
    return base64_string, timestamp

def initiate_payment(phone_number, amount, description=TRANSACTION_DESCRIPTION):
    """Initiate STK push payment"""
    # Format phone number (remove leading 0 or +254)
    if phone_number.startswith("+254"):
        phone_number = phone_number[1:]  # Remove +
    elif phone_number.startswith("0"):
        phone_number = "254" + phone_number[1:]  # Replace 0 with 254
    
    # Generate access token
    access_token = generate_access_token()
    if not access_token:
        return {"error": "Failed to generate access token"}
    
    # Generate password and timestamp
    password, timestamp = generate_password()
    
    # Prepare request
    url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "BusinessShortCode": BUSINESS_SHORT_CODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": TRANSACTION_TYPE,
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": BUSINESS_SHORT_CODE,
        "PhoneNumber": phone_number,
        "CallBackURL": CALLBACK_URL,
        "AccountReference": ACCOUNT_REFERENCE,
        "TransactionDesc": description
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        
        if 'ResponseCode' in response_data and response_data['ResponseCode'] == "0":
            # Success
            return {
                "transaction_id": response_data['CheckoutRequestID'],
                "response_code": response_data['ResponseCode'],
                "response_description": response_data['ResponseDescription']
            }
        else:
            # Failed
            error_message = response_data.get('errorMessage', 'Unknown error')
            return {"error": error_message}
    except Exception as e:
        print(f"Error initiating payment: {str(e)}")
        return {"error": str(e)}

def check_payment_status(checkout_request_id):
    """Check status of STK push payment"""
    # Generate access token
    access_token = generate_access_token()
    if not access_token:
        return "error"
    
    # Generate password and timestamp
    password, timestamp = generate_password()
    
    # Prepare request
    url = "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "BusinessShortCode": BUSINESS_SHORT_CODE,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        
        if 'ResultCode' in response_data:
            if response_data['ResultCode'] == 0:
                return "completed"
            else:
                return "failed"
        else:
            return "pending"
    except Exception as e:
        print(f"Error checking payment status: {str(e)}")
        return "error"

