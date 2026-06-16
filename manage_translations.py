import os
import subprocess
import sys
import re
from collections import Counter

def check_babel_config():
    """Checks babel.cfg for legacy extensions that break in Jinja2 3.x."""
    has_critical = False
    if os.path.exists("babel.cfg"):
        warnings = []
        try:
            with open("babel.cfg", "r") as f:
                content = f.read()
                if "jinja2.ext.autoescape" in content or "jinja2.ext.with_" in content:
                    warnings.append(
                        "Legacy extensions ('jinja2.ext.autoescape' or 'with_') detected.\n"
                        "    Jinja2 3.x has these built-in. Remove them from babel.cfg to avoid errors."
                    )
                    has_critical = True
                
                if "[jinja2:" in content and "[extractors]" not in content:
                    warnings.append(
                        "Missing [extractors] section for Jinja2.\n"
                        "    Add '[extractors]\\njinja2 = jinja2.ext:babel_extract' to the top of babel.cfg"
                    )

                if "method = jinja2" in content:
                    warnings.append("Redundant 'method = jinja2' line detected. Remove it from template sections.")
                
            if warnings:
                print("\n" + "!"*40)
                print("[!] CONFIGURATION WARNINGS:")
                for w in warnings:
                    print(f"  - {w}")
                print("!"*40 + "\n")
        except Exception:
            pass
    return has_critical

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

def run_auto_translate():
    """Automates the filling of empty translations using Google Translate."""
    try:
        import polib
        from deep_translator import GoogleTranslator
    except ImportError:
        print("\n[!] Error: Missing dependencies for auto-translation.")
        print("    Please run: pip install polib deep-translator\n")
        sys.exit(1)

    locales_dir = "translations"
    if not os.path.exists(locales_dir):
        print("[!] No translations directory found.")
        return

    # Regex to find Python named placeholders like %(name)s or %(count)02d
    placeholder_pattern = re.compile(r'%\([^)]+\)[0-9.]*[sdif]')

    for locale in os.listdir(locales_dir):
        # Integrity: Only process directories in the translations folder
        if not os.path.isdir(os.path.join(locales_dir, locale)):
            continue
            
        po_path = os.path.join(locales_dir, locale, "LC_MESSAGES", "messages.po")
        if os.path.exists(po_path):
            print(f"[*] Auto-translating locale: {locale}...")
            po = polib.pofile(po_path)
            # Ensure locale code compatibility for Google Translate (e.g., id, zh-CN)
            target_locale = locale.replace('_', '-')
            translator = GoogleTranslator(source='auto', target=target_locale)
            
            for entry in po:
                if entry.obsolete or entry.msgid_plural:
                    # Skip obsolete entries and plural entries (plurals are complex for auto-translation)
                    continue

                # Check if translation is missing OR if placeholders were corrupted by previous runs
                source_placeholders = placeholder_pattern.findall(entry.msgid)
                target_placeholders = placeholder_pattern.findall(entry.msgstr) if entry.msgstr else []
                
                # Use Counter for exact placeholder matching (including counts)
                needs_translation = not entry.msgstr or (Counter(source_placeholders) != Counter(target_placeholders))

                if needs_translation:
                    try:
                        text_to_translate = entry.msgid
                        # Temporarily replace placeholders with unique tokens the translator won't touch
                        for i, ph in enumerate(source_placeholders):
                            # Replace only first occurrence to handle multiple identical placeholders correctly
                            text_to_translate = text_to_translate.replace(ph, f" __PH{i}__ ", 1)

                        translated = translator.translate(text_to_translate)
                        
                        # Integrity: Skip if translation failed or returned empty
                        if not translated:
                            continue

                        # Restore original placeholders
                        for i, ph in enumerate(source_placeholders):
                            # Use regex sub with lambda to ensure 'ph' is treated as a literal string (no backslash processing)
                            # and to handle potential spacing or case changes (e.g. __ph 0 __) added by the translator
                            translated = re.sub(rf'__\s*PH\s*{i}\s*__', lambda m: ph, translated, flags=re.IGNORECASE)

                        entry.msgstr = translated
                        print(f"    [+] Fixed/Translated: '{entry.msgid[:30]}...' -> '{translated[:30]}...'")
                    except Exception as e:
                        print(f"    [!] Failed to translate '{entry.msgid[:20]}': {e}")
            
            po.save()
            print(f"[*] Saved {locale} catalog.\n")

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
    print("  translate    - Automatically fill empty translations using Google Translate")
    print("  compile      - Compile .po files to .mo files (required for app display)")
    print("="*40 + "\n")

def main():
    if len(sys.argv) < 2:
        print_help()
        return

    # Proactively check for configuration issues common in modern Python environments
    if check_babel_config():
        print("[!] Execution aborted due to configuration errors. Please fix babel.cfg as noted above.")
        sys.exit(1)

    command = sys.argv[1].lower()

    # Centralized extraction parameters to ensure integrity across commands
    # Includes standard Flask-Babel keywords plus full names for robust extraction consistency.
    extract_args = [
        "pybabel", "extract", "-F", "babel.cfg", 
        "-k", "_", "-k", "_l", "-k", "gettext", "-k", "ngettext", "-k", "lazy_gettext",
        "-o", "messages.pot", "."
    ]

    # Check if there are any actual catalogs (locales) to work with
    has_catalogs = os.path.isdir("translations") and any(os.path.isdir(os.path.join("translations", d)) for d in os.listdir("translations"))

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
        print("[+] Extraction complete: messages.pot updated.")
    elif command == "init":
        if len(sys.argv) < 3:
            print("[!] Error: Language code required. Example: python manage_translations.py init fr")
            sys.exit(1)
        # Automatically extract strings if messages.pot is missing
        if not os.path.exists("messages.pot"):
            run_command(extract_args)
        run_command(["pybabel", "init", "-i", "messages.pot", "-d", "translations", "-l", sys.argv[2]])
        print(f"[+] Language '{sys.argv[2]}' initialized in translations/.")
    elif command == "update":
        run_command(extract_args)
        run_command(["pybabel", "update", "-i", "messages.pot", "-d", "translations"])
        print("[+] Update complete: catalogs synchronized with source code.")
    elif command == "translate":
        run_auto_translate()
    elif command == "compile":
        run_command(["pybabel", "compile", "-d", "translations"])
        print("[+] Compilation complete: .mo files generated.")
    else:
        print_help()

if __name__ == "__main__":
    main()