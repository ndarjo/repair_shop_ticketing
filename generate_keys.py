import secrets
import base64

def generate_keys():
    print("\n" + "="*40)
    print("   Repair Shop Security Key Generator")
    print("="*40)
    
    s_key = secrets.token_urlsafe(32)
    b_salt = secrets.token_urlsafe(32)
    # Use urlsafe_b64encode to stay consistent with Fernet's canonical key format
    e_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')
    
    print("\nCopy and paste these lines into your env.local file:\n")
    print(f"SECRET_KEY={s_key}")
    print(f"BLIND_INDEX_SALT={b_salt}")
    print(f"ENCRYPTION_KEY={e_key}")
    
    print("\n" + "="*40 + "\n")

if __name__ == "__main__":
    generate_keys()