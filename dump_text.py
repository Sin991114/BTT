from extract_btt import read_pdf_text

if __name__ == "__main__":
    text = read_pdf_text("BTT Question.pdf")
    print(text[:10000])

