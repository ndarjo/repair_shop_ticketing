import secrets
import base64

def generate_keys():
    print("="*50)
    print("   Repair Shop Security Key Generator")
    print("="*50)
    
    print(f"\nSECRET_KEY (for sessions):")
    print(secrets.token_urlsafe(32))
    
    print(f"\nENCRYPTION_KEY (for PII encryption - Base64):")
    print(base64.b64encode(secrets.token_bytes(32)).decode('utf-8'))
    print("\n" + "="*50)

if __name__ == "__main__":
    generate_keys()