## 🌐 Internationalization (i18n)

The system supports dynamic language discovery based on compiled translation files. To manage translations, the system uses **Flask-Babel** and a provided helper script.

### Workflow for Adding a New Language (e.g., French `fr`)

1. **Extract:** Scan the source code and generate the `messages.pot` template.
   ```bash
   python manage_translations.py extract
   ```
   *Note: If you encounter an `AttributeError` regarding `jinja2.ext.autoescape`, ensure your `babel.cfg` does not include legacy extensions. See TROUBLESHOOTING.md for details.*

2. **Initialize:** Create the translation catalog for the specific language.
   ```bash
   python manage_translations.py init fr
   ```
3. **Translate:** Open `translations/fr/LC_MESSAGES/messages.po` and fill in the translated strings in `msgstr`.
4. **Compile:** Generate the machine-readable files. **Note: The language selection in Profile and Onboarding only lists languages that have been compiled.**
   ```bash
   python manage_translations.py compile
   ```

### Updating Existing Translations
If you modify the source code or templates, use the update command to scan for new strings and merge them into existing catalogs:
```bash
python manage_translations.py update

#Auto-Translate: Fills in the blanks automatically.
python manage_translations.py translate

# After editing the new strings in your .po files, re-compile:
python manage_translations.py compile
```
