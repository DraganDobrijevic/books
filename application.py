import os
import requests

from flask import Flask, session, jsonify, redirect, render_template, request, make_response
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import login_required, error

app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

app.config["JSON_SORT_KEYS"] = False

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


# Set up database
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))


@app.route("/")
def index():
    session.clear()
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    # Forget any user_id
    session.clear()

    if request.method == "POST":
        username = request.form.get("username")
        notAvailable = db.execute("SELECT username FROM users WHERE username = :username", 
                                    {"username": username}).fetchall()
        if notAvailable != []:
            return render_template("apology.html", message="Username is not available")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")
        fullname = request.form.get("fullName")
        if not username and not fullname and not password and not confirmation:
            return redirect("/register")
        if not username:
            return render_template("apology.html", message="Missing username")
        if not fullname:
            return render_template("apology.html", message="Missing full name")
        if not password:
            return render_template("apology.html", message="Missing password")
        if password != confirmation:
            return render_template("apology.html", message="The passwords do not match!")
        hash = generate_password_hash(password, method='pbkdf2:sha256', salt_length=8)
        db.execute("INSERT INTO users (username, password, fullname) VALUES (:username, :password, :fullname)",
                            {"username": username, "password": hash, "fullname": fullname})
        rows = db.execute("SELECT * FROM users WHERE username = :username", {"username": username}).fetchall()
        db.commit()
        session["user_id"] = rows[0]["id"]
        return render_template("login.html")
    else:
        return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return render_template("apology.html", message="Missing username or password")

        # Ensure password was submitted
        elif not request.form.get("password"):
            return render_template("apology.html", message="Missing password")

        username=request.form.get("username")
        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                            {"username": username}).fetchall()

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["password"], request.form.get("password")):
            return render_template("apology.html", message="Invalid username and/or password")

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        return redirect("/search")

    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/search", methods=["GET", "POST"])
@login_required
def search():

    if request.method == "GET":
        return render_template("search.html")
    else:
        search = request.form.get("search")
        inputs = request.form.get("books")
        if not search or not inputs:
            return redirect("/search")
        inputs = "%{}%".format(inputs)
        if search == "isbn":
            books = db.execute("SELECT * FROM books WHERE isbn LIKE :inputs", {"inputs": inputs}).fetchall()
            if len(books) == 0:
                x = True
                return render_template("books.html", books="There is no book in our database with this ISBN", x=x)
        if search == "title":
            books = db.execute("SELECT * FROM books WHERE title LIKE :inputs", {"inputs": inputs}).fetchall()
            if len(books) == 0:
                x = True
                return render_template("books.html", books="There is no book in our database with this title", x=x)
        if search == "author":
            books = db.execute("SELECT * FROM books WHERE author LIKE :inputs", {"inputs": inputs}).fetchall()
            if len(books) == 0:
                x = True
                return render_template("books.html", books="There are no books in our database with this author name", x=x)
        
        return render_template("books.html", books=books)


@app.route("/search/<string:isbn>", methods=["GET", "POST"])
@login_required
def booki(isbn):
    """List details informations about a single book"""

    res = requests.get("https://www.goodreads.com/book/review_counts.json", params={"key": "urPXtC1i4qp3hQeFm7gPw", "isbns": isbn})
    book = db.execute("SELECT * FROM books WHERE isbn = :isbn", {"isbn": isbn}).fetchone()
    api = res.json()
    
    n = db.execute("SELECT rated FROM reviews WHERE books_isbn = :isbn", {"isbn": isbn}).fetchall()
    old_count = int(api['books'][0]['work_ratings_count'])
    old_avg = float(api['books'][0]['average_rating'])

    s = 0
    new_count = 0
    for i in n:
        i = i[0]
        if i == None:
            continue
        s += i
        new_count += 1

    if new_count == 0:
        new_avg = "No score"
    else:
        new_avg = s / new_count 
        new_avg = round(new_avg, 2)

    permit = 7
    if request.method == "POST":
        review = request.form.get("review")
        rated = request.form.get("rated")
        username = db.execute("SELECT username FROM users WHERE id = :id", {"id": session["user_id"]}).fetchone()
        book = db.execute("SELECT * FROM books WHERE isbn = :isbn", {"isbn": isbn}).fetchone()
        rev_permit = db.execute("SELECT books_isbn FROM reviews WHERE users_id = :id AND books_isbn = :isbn", {"id": session["user_id"], "isbn": isbn}).fetchone()
        if not rev_permit:
            permit = 1
            db.execute("INSERT INTO reviews (books_isbn, review, users_id, username, rated) VALUES (:book_isbn, :review, :user_id, :username, :rated)",
                    {"book_isbn": isbn, "review": review, "user_id": session["user_id"], "username": username[0], "rated": rated})
        else:
            permit = 0
    reviews = db.execute("SELECT review, username, rated FROM reviews WHERE books_isbn = :isbn", {"isbn": isbn}).fetchall()
    db.commit()
    return render_template("book.html", book=book, reviews=reviews, old_count=old_count, old_avg=old_avg, new_count=new_count, new_avg=new_avg, permit=permit)


@app.route("/search/api/<isbn>")
@app.route("/api/<isbn>")
def api(isbn):
    try:
        book = db.execute("SELECT * FROM books WHERE isbn = :isbn", {"isbn": isbn}).fetchone()
        res = requests.get("https://www.goodreads.com/book/review_counts.json", params={"key": "xxxxxxxxxxxxxx", "isbns": isbn})
        api=res.json()     
    except:
        return error(jsonify(error="Not found",status=404,message="Requested ISBN is not in our database"), 404)
        
    return jsonify(title=book.title,
                   author=book.author,
                   year=book.year,
                   isbn=book.isbn,
                   review_count=api['books'][0]['reviews_count'],
                   average_score=api['books'][0]['average_rating'])

