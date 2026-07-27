import subprocess
import tempfile
import os


def has_extractable_text(pdf_bytes, min_chars=30):
    import pdfplumber
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(pdf_bytes)
        path = f.name
    try:
        with pdfplumber.open(path) as pdf:
            total = sum(len((p.extract_text() or '')) for p in pdf.pages)
        return total >= min_chars
    finally:
        os.remove(path)


def ocr_extract_lines(pdf_bytes):
    """OCR best-effort via tesseract, reconstruindo linhas por proximidade vertical
    das palavras. Resultado é aproximado — sempre precisa de conferência manual
    antes de virar OFX (valores e sinais podem sair errados)."""
    import pytesseract
    from pytesseract import Output
    from PIL import Image

    with tempfile.TemporaryDirectory() as d:
        pdf_path = os.path.join(d, 'in.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
        subprocess.run(['pdftoppm', '-png', '-r', '300', pdf_path, os.path.join(d, 'page')],
                        check=True, capture_output=True)
        page_files = sorted(f for f in os.listdir(d) if f.endswith('.png'))

        all_lines = []
        for pf in page_files:
            img = Image.open(os.path.join(d, pf))
            data = pytesseract.image_to_data(img, lang='por', output_type=Output.DICT)
            words = []
            for i in range(len(data['text'])):
                txt = data['text'][i].strip()
                if txt:
                    words.append((data['top'][i], data['left'][i], txt))
            words.sort(key=lambda w: (w[0], w[1]))
            lines = []
            current_line = []
            current_top = None
            for top, left, txt in words:
                if current_top is None or abs(top - current_top) <= 8:
                    current_line.append((left, txt))
                    current_top = top if current_top is None else current_top
                else:
                    lines.append(' '.join(t for _, t in sorted(current_line)))
                    current_line = [(left, txt)]
                    current_top = top
            if current_line:
                lines.append(' '.join(t for _, t in sorted(current_line)))
            all_lines.extend(lines)
    return all_lines
