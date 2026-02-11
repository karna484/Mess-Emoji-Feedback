from flask import Flask, render_template, request, redirect, url_for, flash
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from openpyxl import Workbook
import os
import json
from google.oauth2.service_account import Credentials

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ---------------- GOOGLE SHEETS SETUP ---------------- #

creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(creds_dict, scopes=scope)

client = gspread.authorize(creds)

SPREADSHEET_NAME = "Mess Emoji Feedback"
spreadsheet = client.open(SPREADSHEET_NAME)
sheet = spreadsheet.sheet1

feedback_active = False

# ---------------- INITIALIZE SHEET STRUCTURE ---------------- #

def initialize_sheet():
    sheet.clear()

    # Start & End Time
    sheet.update('A1', [["Feedback Start Time", "Feedback End Time"]])
    sheet.update('A2', [["Not Started", "Not Ended"]])

    # Overall Summary
    sheet.update('A3', [["Total Feedback", "Average Rating"]])
    sheet.update('A4', [[0, 0]])

    # Overall Rating Count
    rating_types = ["Very Bad", "Bad", "Average", "Good", "Very Good"]
    sheet.update('A6', [rating_types])
    sheet.update('A7', [[0, 0, 0, 0, 0]])

    # Meal-wise Rating Count
    sheet.update('A9', [["Meal", "Very Bad", "Bad", "Average", "Good", "Very Good"]])
    sheet.update('A10', [["Breakfast", 0, 0, 0, 0, 0]])
    sheet.update('A11', [["Lunch", 0, 0, 0, 0, 0]])
    sheet.update('A12', [["Dinner", 0, 0, 0, 0, 0]])

    # Issue Summary
    sheet.update('A14', [["Issue Type", "Count"]])
    sheet.update('A15', [["Too Spicy", 0]])
    sheet.update('A16', [["Not Cooked Well", 0]])
    sheet.update('A17', [["Less Side Dishes", 0]])
    sheet.update('A18', [["Not Cleaned Well", 0]])

    # Feedback Data Header
    sheet.update('A20', [["Meal", "Rating", "Issues", "Timestamp"]])

initialize_sheet()

# ---------------- UPDATE SUMMARY ---------------- #

def update_summary():
    all_rows = sheet.get_all_values()
    data_rows = all_rows[20:]  # feedback starts after row 20

    rating_types = ["Very Bad", "Bad", "Average", "Good", "Very Good"]
    meals = ["Breakfast", "Lunch", "Dinner"]

    rating_score_map = {
        "Very Bad": 1,
        "Bad": 2,
        "Average": 3,
        "Good": 4,
        "Very Good": 5
    }

    overall_rating_count = {r: 0 for r in rating_types}
    meal_rating_count = {meal: {r: 0 for r in rating_types} for meal in meals}
    issue_count = {
        "Too Spicy": 0,
        "Not Cooked Well": 0,
        "Less Side Dishes": 0,
        "Not Cleaned Well": 0
    }

    total_feedback = 0
    total_score = 0

    for row in data_rows:
        if len(row) >= 3:
            meal = row[0].strip()
            rating = row[1].strip()
            issues = row[2]

            # Skip invalid meal or rating
            if meal not in meals:
                continue
            if rating not in rating_types:
                continue

            total_feedback += 1

            overall_rating_count[rating] += 1
            meal_rating_count[meal][rating] += 1
            total_score += rating_score_map.get(rating, 0)

            for issue in issue_count:
                if issue in issues:
                    issue_count[issue] += 1

    average = round(total_score / total_feedback, 2) if total_feedback > 0 else 0

    # Update overall summary
    sheet.update('A4', [[total_feedback, average]])

    # Update overall rating count
    sheet.update('A7', [[overall_rating_count[r] for r in rating_types]])

    # Update meal-wise rating
    sheet.update('B10', [[meal_rating_count["Breakfast"][r] for r in rating_types]])
    sheet.update('B11', [[meal_rating_count["Lunch"][r] for r in rating_types]])
    sheet.update('B12', [[meal_rating_count["Dinner"][r] for r in rating_types]])

    # Update issue counts
    sheet.update('B15', [[issue_count["Too Spicy"]]])
    sheet.update('B16', [[issue_count["Not Cooked Well"]]])
    sheet.update('B17', [[issue_count["Less Side Dishes"]]])
    sheet.update('B18', [[issue_count["Not Cleaned Well"]]])


# ---------------- STUDENT PAGE ---------------- #

@app.route('/')
def index():
    global feedback_active

    if not feedback_active:
        return "<h2>Feedback is currently closed.</h2>"

    summary = sheet.get('A4:B4')
    total = summary[0][0]
    average = summary[0][1]

    return render_template('index.html', total=total, average=average)

# ---------------- SUBMIT ---------------- #

@app.route('/submit', methods=['POST'])
def submit():
    global feedback_active

    if not feedback_active:
        return "<h2>Feedback is currently closed.</h2>"

    meal = request.form['meal']
    rating_number = request.form['rating']
    issues = request.form.getlist('issues')
    issues_text = ", ".join(issues) if issues else "None"

    rating_map = {
        "1": "Very Bad",
        "2": "Bad",
        "3": "Average",
        "4": "Good",
        "5": "Very Good"
    }

    rating_word = rating_map.get(rating_number)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sheet.append_row([meal, rating_word, issues_text, timestamp])

    update_summary()

    flash("🎉 Feedback Noted Successfully!")
    return redirect(url_for('index'))

# ---------------- ADMIN ---------------- #

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    global feedback_active

    if request.method == 'POST':
        action = request.form['action']

        if action == "start":
            feedback_active = True
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.update('A2', [[start_time, "Not Ended Yet"]])
            flash("Feedback Started")

        elif action == "end":
            feedback_active = False
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.update('B2', [[end_time]])
            flash("Feedback Ended")

    return render_template('admin.html', active=feedback_active)

# ---------------- RESET WITH BACKUP ---------------- #

@app.route('/reset', methods=['POST'])
def reset():

    if not os.path.exists("backups"):
        os.makedirs("backups")

    backup_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"backups/backup_{backup_time}.xlsx"

    all_data = sheet.get_all_values()

    wb = Workbook()
    ws = wb.active

    for row in all_data:
        ws.append(row)

    wb.save(filename)

    sheet.clear()
    initialize_sheet()

    flash("Backup saved & Sheet Reset Successfully")

    return redirect(url_for('admin'))

# ---------------- RUN ---------------- #

if __name__ == "__main__":
    app.run()


