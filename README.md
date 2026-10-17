## Build for Windows

```
pyinstaller --noconfirm --onedir --windowed --name="HR_System" main.py
```

```
docker run --rm -v "$(pwd):/src" cdrx/pyinstaller-windows "pyinstaller --onedir --windowed --name="HR_System2" main.py"
```

```
docker run --rm -v "$(pwd):/src" tobix/pyinstaller-windows "pip install -r requirements.txt && pyinstaller --onedir --windowed main.py"
```
