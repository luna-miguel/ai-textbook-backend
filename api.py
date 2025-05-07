from flask import Flask, request, redirect, url_for, send_file
from flask_cors import CORS
import json
import logging
import os
from werkzeug.utils import secure_filename
from io import BytesIO

from pypdf import PdfReader
from docx import Document
import fpdf

from openai import OpenAI

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, methods=['POST'], allow_headers=['Content-Type'])

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(debug=True, host='0.0.0.0', port=port)

# Uploaded files go here
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Allowed file types
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}

# ChatGPT responses go here (in JSON format)
RESPONSE_FOLDER = 'responses'
app.config['RESPONSE_FOLDER'] = RESPONSE_FOLDER

text = []

# Check i
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Ensure upload and response directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESPONSE_FOLDER, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/upload', methods=['POST'])
def upload():
    try:
        if 'file' not in request.files:
            logger.error("No file part in request")
            return {'error': 'No file part in the request'}, 400
        file = request.files['file']
        if file.filename == '':
            logger.error("No file selected")
            return {'error': 'No file selected'}, 400

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            logger.info(f"Saving file to {filepath}")
            file.save(filepath)

            if not os.path.exists(filepath):
                logger.error(f"File not found at {filepath}")
                return {'error': 'File not found'}, 400

            filename, extension = os.path.splitext(filepath)
            logger.info(f"Processing file with extension: {extension}")

            processed_text = []
            chunk = ""

            if extension == ".pdf":
                reader = PdfReader(filepath)
                for i in range(len(reader.pages)):
                    chunk += reader.pages[i].extract_text(extraction_mode="layout", layout_mode_space_vertically=False)
                    chunk = " ".join(chunk.split())
                    if len(chunk) > 2000:
                        processed_text.append(chunk)
                        chunk = ""   
                processed_text.append(chunk)

            if extension == ".docx":
                doc = Document(filepath)
                for para in doc.paragraphs:
                    chunk += para.text
                    if len(chunk) > 2000:
                        processed_text.append(chunk)
                        chunk = ""
                processed_text.append(chunk)

            if extension == ".txt":
                f = open(filepath, "r")
                lines = f.readlines()
                for line in lines:
                    chunk += line
                    if len(chunk) > 2000:
                        processed_text.append(chunk)
                        chunk = ""
                processed_text.append(chunk)
            
            return {'text': processed_text}, 200

        else:
            return {'error': 'Invalid file type'}, 422

    except Exception as e:
        logger.error(f"Error in upload: {str(e)}")
        return {'error': str(e)}, 500

client = OpenAI( api_key=os.environ.get("OPENAI_API_KEY") )

prompt_flashcards = "You are to use the following text from the user to identify every key concept and create a summary of its definition, like a flashcard. \
Create a key concept as a singular noun or term. You must identify the concept and state what it is before constructing a definition. \
The definition should define what the key concept is. It should be found using only information in the text. \
Definitions for each concept should be ONE full sentence long, at most. \
Return every key concept and definition found in JSON format, each with objects 'concept' and 'definition'. \
Only return the resulting JSON file."

@app.route('/generate_cards', methods=['POST'])
def generate_cards():
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            logger.error("No text content in request")
            return {'error': 'No text content provided'}, 400

        text = data['text']
        logger.info(f"Processing {len(text)} chunks for flashcards")
        outputs = []
        for chunk in text:
            response = client.responses.create(
                model="gpt-4o-mini",
                input=[
                {"role": "system", "content": prompt_flashcards},
                {"role": "user", "content": chunk}
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "textbook_summarization",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "all": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "concept": {"type": "string"},
                                            "definition": {"type": "string"},
                                        },
                                        "required": ["concept", "definition"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["all"],
                            "additionalProperties": False,
                        },
                        "strict": True,
                    },
                },
            ) 
            outputs.append(json.loads(response.output_text))

        res = {"all": []}
        for output in outputs:
            res["all"].extend(output["all"])
        
        path = os.path.join(app.config['RESPONSE_FOLDER'], "flashcards.json")
        with open(path, "w") as json_file:
            json.dump(res, json_file, indent=4)

        return res

    except Exception as e:
        logger.error(f"Error in generate_cards: {str(e)}")
        return {'error': str(e)}, 500

prompt_quiz = "You are to use the following text to generate a multiple-choice style quiz. \
Each quiz question should have exactly four answer choices, with one correct and the other three incorrect. \
Answer choices for each question should be ONE full sentence long, at most. Keep these choices around the same length in words as much as possible. \
When making questions about certain concepts in the text, make sure the questions can be solved using ONLY information from the given text. \
Do not use information from any other sources besides the given text to create the quiz questions. \
Generate as many questions as necessary, not too few but also not too many as to make them redundant. \
Return the questions and answer choices in JSON format, with objects 'question', 'correct_answer', and the array 'incorrect_answer'. \
Only return the resulting JSON file."

@app.route('/generate_quiz', methods=['POST'])
def generate_quiz():
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            logger.error("No text content in request")
            return {'error': 'No text content provided'}, 400

        text = data['text']
        logger.info(f"Processing {len(text)} chunks for quiz")
        outputs = []
        for chunk in text:
            response = client.responses.create(
                model="gpt-4o-mini",
                input=[
                {"role": "system", "content": prompt_quiz},
                {"role": "user", "content": chunk}
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "textbook_summarization",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "all": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "question": {"type": "string"},
                                            "correct_answer": {"type": "string"},
                                            "incorrect_answers": {
                                                "type": "array",
                                                "items": { "type": "string", }
                                            },
                                        },
                                        "required": ["question", "correct_answer", "incorrect_answers"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["all"],
                            "additionalProperties": False,
                        },
                        "strict": True,
                    },
                },
            ) 
            outputs.append(json.loads(response.output_text))

        res = {"all": []}
        for output in outputs:
            res["all"].extend(output["all"])
        
        path = os.path.join(app.config['RESPONSE_FOLDER'], "quiz.json")
        with open(path, "w") as json_file:
            json.dump(res, json_file, indent=4)

        return res

    except Exception as e:
        logger.error(f"Error in generate_quiz: {str(e)}")
        return {'error': str(e)}, 500

def sanitize_text(text):
    """Replace problematic characters with their ASCII equivalents."""
    replacements = {
        "'": "'",  # Smart single quote to regular single quote
        '"': '"',  # Smart double quote to regular double quote
        '–': '-',  # En dash to hyphen
        '—': '--', # Em dash to double hyphen
        '…': '...', # Ellipsis to three dots
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

@app.route('/export', methods=['POST'])
def export():
    data = request.get_json()
    if not data:
        return {"error": "No data received"}, 400

    try:
        pdf = fpdf.FPDF(format='letter')
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pages = 1

        def add_header():
            pdf.set_font("Arial", size=10)
            pdf.cell(0, 10, f"{pages}", ln=True, align="R")
            pdf.set_font("Arial", size=12, style="B")
            pdf.cell(0, 10, "Created with AI Textbook Quiz Creator", ln=True)
            pdf.cell(0, 10, "Name: _____________________", ln=True)
            pdf.cell(0, 10, "Date: _____________________", ln=True)
            pdf.ln(10)

        add_header()
        choices = ["a", "b", "c", "d"]

        for i in range(len(data)):
            try:
                # Add new page every 2 questions
                if i > 0 and i % 2 == 0:
                    pdf.add_page()
                    pages += 1
                    add_header()

                item = data[i]
                obj, questions = item[0], item[1]

                # Question
                pdf.set_font("Arial", style="B")
                question_text = sanitize_text(f"{i+1}. {obj['question']}")
                pdf.multi_cell(0, 10, question_text)
                pdf.ln(3)

                # Answer choices: letter (indented), then answer text flush with question
                pdf.set_font("Arial")
                for j in range(len(questions)):
                    answer_text = sanitize_text(f"{questions[j]}")
                    pdf.cell(15, 10, f"{choices[j]}.", ln=0)
                    pdf.multi_cell(0, 10, answer_text)
                pdf.ln(8)

            except Exception as e:
                logger.error(f"Error processing question {i}: {str(e)}")
                return {"error": f"PDF generation failed at question {i}: {str(e)}"}, 500

        # Answer key
        pdf.add_page()
        pages += 1
        add_header()
        pdf.cell(0, 10, "ANSWER KEY", ln=True)
        pdf.ln(10)

        for i in range(len(data)):
            try:
                if i > 0 and i % 15 == 0:
                    pdf.add_page()
                    pages += 1
                    add_header()
                    pdf.cell(0, 10, "ANSWER KEY", ln=True)
                    pdf.ln(10)
                item = data[i]
                obj, questions = item[0], item[1]
                answer_text = sanitize_text(f"{i+1}: ({choices[questions.index(obj['correct_answer'])]})")
                pdf.cell(20, 10, "")
                pdf.cell(0, 10, answer_text, ln=True)
            except Exception as e:
                logger.error(f"Error processing answer key {i}: {str(e)}")
                return {"error": f"PDF generation failed at answer key {i}: {str(e)}"}, 500

        pdf_bytes = BytesIO()
        pdf.output(pdf_bytes)
        pdf_bytes.seek(0)

        return send_file(
            pdf_bytes,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='export.pdf'
        )

    except Exception as e:
        logger.error(f"Error in PDF generation: {str(e)}")
        return {"error": f"PDF generation failed: {str(e)}"}, 500

@app.route('/health', methods=['GET'])
def health_check():
    return {'status': 'healthy'}, 200
