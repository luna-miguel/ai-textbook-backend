from flask import Flask, request, redirect, url_for, send_file
import json

import os
from werkzeug.utils import secure_filename

from pypdf import PdfReader
from docx import Document
import fpdf

from openai import OpenAI

app = Flask(__name__)

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

@app.route('/upload', methods=['POST'])
def upload():

    if 'file' not in request.files:
        return {'error': 'No file part in the request'}, 400
    file = request.files['file']
    if file.filename == '':
        return {'error': 'No file selected'}, 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(filepath):
            return {'error': 'File not found'}, 400

        filename, extension = os.path.splitext(filepath)

        global text
        text = []
        chunk = ""

        if extension == ".pdf":
            reader = PdfReader(filepath)
            for i in range(len(reader.pages)):
                chunk += reader.pages[i].extract_text(extraction_mode="layout", layout_mode_space_vertically=False)
                chunk = " ".join(chunk.split()) # Seemingly fixes odd formatting of read string from PDF
                if len(chunk) > 2000:
                    text.append(chunk)
                    chunk = ""   
            text.append(chunk)

        if extension == ".docx":
            doc = Document(filepath)
            for para in doc.paragraphs:
                chunk += para.text
                if len(chunk) > 2000:
                    text.append(chunk)
                    chunk = ""
            text.append(chunk)


        if extension == ".txt":
            f = open(filepath, "r")
            lines = f.readlines()
            for line in lines:
                chunk += line
                if len(chunk) > 2000:
                    text.append(chunk)
                    chunk = ""
            text.append(chunk)
        
        return {'text': text}, 200

    else:
        return {'error': 'Invalid file type'}, 422

client = OpenAI( api_key=os.environ.get("OPENAI_API_KEY") )

prompt_flashcards = "You are to use the following text from the user to identify every key concept and create a summary of its definition, like a flashcard. \
Create a key concept as a singular noun or term. You must identify the concept and state what it is before constructing a definition. \
The definition should define what the key concept is. It should be found using only information in the text. \
Definitions for each concept should be ONE full sentence long, at most. \
Return every key concept and definition found in JSON format, each with objects 'concept' and 'definition'. \
Only return the resulting JSON file."

@app.route('/generate_cards', methods=['POST'])
def generate_cards():
    global text
    outputs = []
    try:
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
        return {'error': 'Something went wrong. Please try again.'}, 400

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
    global text
    outputs = []

    try:
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
        return {'error': 'Something went wrong. Please try again.'}, 400

@app.route('/export', methods=['POST'])
def export():
    data = request.get_json()
    if not data:
        return {"error": "No data received"}, 400

    pdf = fpdf.FPDF(format='letter') 
    pdf.set_font("Times", size=12) 
    pdf.set_left_margin(10)
    pages = 0

    choices = ["a", "b", "c", "d"]
    indent = " " * 8
    for i in range(len(data)):

        if i % 5 == 0:
            pdf.add_page() # Create new page
            pages += 1
            pdf.multi_cell(0, 0, txt=f"{pages}", align="R")
            pdf.set_font("Times", size=12, style="B") 
            pdf.multi_cell(0, 5, txt="Created with AI Textbook Quiz Creator", align="L")
            pdf.multi_cell(0, 5, txt="Name: _____________________", align="L")
            pdf.multi_cell(0, 5, txt="Date: _____________________", align="L")
            pdf.set_font("Times", size=12) 
            pdf.multi_cell(0, 10)
        
        item = data[i]
        obj, questions = item[0], item[1]

        pdf.set_font("Times", size=12, style="B") 
        pdf.multi_cell(0,5, f"{i+1}. {obj['question']}", align="L")
        pdf.multi_cell(0,5)
        pdf.set_font("Times", size=12) 

        for i in range(len(questions)):
            pdf.multi_cell(0, 5, f"{indent + choices[i]}.\t{questions[i]}")

        pdf.multi_cell(0, 10)

    for i in range(len(data)):
        if i % 15 == 0:
            pdf.add_page() # Create new page
            pages += 1
            pdf.multi_cell(0, 0, txt=f"{pages}", align="R")
            pdf.set_font("Times", size=12, style="B") 
            pdf.multi_cell(0, 5, txt="Created with AI Textbook Quiz Creator", align="L")
            pdf.multi_cell(0, 5, txt="ANSWER KEY", align="L")
            pdf.set_font("Times", size=12) 
            pdf.multi_cell(0, 10)
            
        item = data[i]
        obj, questions = item[0], item[1]

        pdf.set_font("Times", size=12, style="B") 
        pdf.multi_cell(0, 8, f"{i+1}: {indent} ({choices[questions.index(obj['correct_answer'])]})", align="L")
        pdf.set_font("Times", size=12) 


    res = os.path.join(app.config['RESPONSE_FOLDER'], "export.pdf")
    pdf.output(res)

    return send_file(res, as_attachment=True, download_name="export.pdf")
