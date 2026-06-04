import os
import subprocess
import sys

def run_command(cmd):
    """Executes a shell command and handles errors."""
    print(f"Executing: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"\n[!] Error: Command failed with return code {e.returncode}")
        sys.exit(e.returncode)
    except FileNotFoundError:
        print("\n[!] Error: 'pybabel' command not found. Please ensure Flask-Babel is installed in your virtual environment.")
        sys.exit(1)

def print_help():
    """Prints usage information."""
    print("\n" + "="*40)
    print("   Repair Shop Translation Manager")
    print("="*40)
    print("Usage: python manage_translations.py <command> [args]")
    print("\nCommands:")
    print("  extract      - Scan project and extract all strings into messages.pot")
    print("  init <code>  - Initialize a new language (e.g., 'id', 'es', 'fr')")
    print("  update       - Update all existing translation files with new strings")
    print("  compile      - Compile .po files to .mo files (required for app display)")
    print("="*40 + "\n")

def main():
    if len(sys.argv) < 2:
        print_help()
        return

    command = sys.argv[1].lower()

    # Centralized extraction parameters to ensure integrity across commands
    # Includes standard Flask-Babel keywords for gettext (_) and lazy_gettext (_l)
    extract_args = ["pybabel", "extract", "-F", "babel.cfg", "-k", "_", "-k", "_l", "-o", "messages.pot", "."]

    # Check if there are any actual catalogs (locales) to work with
    has_catalogs = os.path.exists("translations") and any(os.path.isdir(os.path.join("translations", d)) for d in os.listdir("translations"))

    # Safety check: Ensure the translations directory exists for update and compile commands
    if not has_catalogs:
        if command == "compile":
            print("\n[*] No locale catalogs found in 'translations/'. Skipping compilation.")
            print("    (The application will default to English strings from the source code.)\n")
            return
        elif command == "update":
            print("\n[!] Error: No language catalogs found.")
            print("    You must initialize at least one language (e.g., 'init id') before you can update strings.")
            print("    Example: python manage_translations.py init id\n")
            sys.exit(1)

    if command == "extract":
        run_command(extract_args)
    elif command == "init":
        if len(sys.argv) < 3:
            print("[!] Error: Language code required. Example: python manage_translations.py init fr")
            sys.exit(1)
        # Automatically extract strings if messages.pot is missing
        if not os.path.exists("messages.pot"):
            run_command(extract_args)
        run_command(["pybabel", "init", "-i", "messages.pot", "-d", "translations", "-l", sys.argv[2]])
    elif command == "update":
        run_command(extract_args)
        run_command(["pybabel", "update", "-i", "messages.pot", "-d", "translations"])
    elif command == "compile":
        run_command(["pybabel", "compile", "-d", "translations"])
    else:
        print_help()

if __name__ == "__main__":
    main()