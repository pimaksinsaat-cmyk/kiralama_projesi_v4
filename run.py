from app import create_app

# __init__.py'deki fabrikamızı çağırarak uygulamayı oluştur
app = create_app()

if __name__ == '__main__':
    # Sadece 'python run.py' komutuyla çalıştırıldığında devreye girer
     app.run(debug=True, host="127.0.0.1", port=5000)