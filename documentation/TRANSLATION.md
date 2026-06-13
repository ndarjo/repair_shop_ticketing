
### Updating Existing Translations
If you modify the source code or templates, use the update command to scan for new strings and merge them into existing catalogs:
```bash
python manage_translations.py update

#extract translation file
python manage_translations.py extract

#update translation file
python manage_translations.py update

#initialize language, i.e french
python manage_translations.py init fr

#Auto-Translate: Fills in the blanks automatically.
python manage_translations.py translate

# After editing the new strings in your .po files, re-compile:
python manage_translations.py compile
```
