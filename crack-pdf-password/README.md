# PDF Password Generator & Cracker

This Python script helps generate possible password combinations based on a specific pattern and attempts to crack a password-protected PDF file using `pdfcrack`.

## 📄 Description

The script generates password strings in the format:

```
[00000-99999][DDMMYY]
```

For example: `12345010190`, where `12345` is a 5-digit number and `010190` is a date in DDMMYY format (e.g., 01-Jan-1990).

It supports multithreading to run multiple cracking jobs concurrently over a range of years.

---

## 🚀 Usage

### Generate passwords and crack a PDF:

```bash
./generate_pass.py --generate-strings --crack-pdf protected.pdf --start-year 1985 --end-year 2005
```

### Arguments:

| Argument            | Description                                      | Default             |
|---------------------|--------------------------------------------------|---------------------|
| `--generate-strings`| Generate password wordlists                      | `False`             |
| `--crack-pdf`       | Path to the PDF file to crack                    | `None`              |
| `--start-year`      | Start year for date-based suffix generation      | `1985`              |
| `--end-year`        | End year for date-based suffix generation        | `1985`              |
| `--concurrent-jobs` | Max number of concurrent cracking threads        | `os.cpu_count()`    |

---

## 🧠 Example

This will:
- Generate passwords from `00000` to `99999`
- Combine with every date from 01-Jan-1985 to 31-Dec-2005 (DDMMYY format)
- Save those combinations to `generated_strings_<YEAR>.txt`
- Attempt to crack the PDF using `pdfcrack`

```bash
./generate_pass.py --generate-strings --crack-pdf secret.pdf --start-year 1990 --end-year 1992
```

---

## 🛠 Requirements

- Python 3.6+
- `pdfcrack` (must be installed and in your system's PATH)

To install `pdfcrack` on Debian/Ubuntu:

```bash
sudo apt install pdfcrack
```

---

## 📂 Output Files

- `generated_strings_<YEAR>.txt`: Passwords generated for that year.
- `generated_strings_<YEAR>_out.log`: Output from `pdfcrack`.
- `generated_strings_<YEAR>_err.log`: Error logs (if any).

---

## ⚠️ Warning

This tool is for educational and ethical purposes only. Do **not** use it on files you do not have permission to access.

---

## 🧑‍💻 License

GNU GPL v3
