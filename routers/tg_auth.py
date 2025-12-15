# stylist-backend/routers/tg_auth.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import timedelta, datetime # <-- ДОБАВЛЕН datetime

from database import get_db
from models import User 
from schemas import Token 
from utils.auth import create_access_token
from utils.telegram_validator import validate_init_data 

router = APIRouter(tags=["Telegram Auth"])

@router.post("/tg-login", response_model=Token)
async def telegram_login(payload: dict, db: Session = Depends(get_db)):
    """
    Авторизация пользователя Telegram Mini App.
    Принимает 'init_data' и возвращает JWT-токен, если данные валидны.
    """
    init_data = payload.get("init_data")
    if not init_data:
        raise HTTPException(400, "init_data is required")

    # 1. Валидация init_data: получаем ID и полные данные
    validation_result = validate_init_data(init_data) # <-- ИЗМЕНЕНИЕ: Вызываем функцию, возвращающую кортеж
    
    if not validation_result:
        # 401 Unauthorized, если initData не прошел проверку подписи
        raise HTTPException(
            status_code=401, 
            detail="Недействительные или скомпрометированные данные Telegram (initData)"
        )
        
    tg_user_id, tg_user_data = validation_result # <-- ИЗМЕНЕНИЕ: Распаковываем результат

    # 2. Находим или создаем пользователя
    user = db.query(User).filter(User.tg_id == tg_user_id).first()
    
    # Извлекаем данные, которые нужно сохранить/обновить
    first_name = tg_user_data.get('first_name')
    last_name = tg_user_data.get('last_name')
    username = tg_user_data.get('username')
    
    if not user:
        # Если пользователя нет, создаем его с полными данными
        print(f"Creating new user with tg_id: {tg_user_id}")
        new_user = User(
            tg_id=tg_user_id,
            first_name=first_name, # <-- ДОБАВЛЕНО
            last_name=last_name,   # <-- ДОБАВЛЕНО
            username=username,     # <-- ДОБАВЛЕНО
            last_login=datetime.utcnow() # <-- ДОБАВЛЕНО
        ) 
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        user = new_user
    else:
        # Обновляем имя, юзернейм и время последнего входа
        user.first_name = first_name
        user.last_name = last_name # <-- ДОБАВЛЕНО
        user.username = username
        user.last_login = datetime.utcnow() # <-- ДОБАВЛЕНО
        db.commit()
        db.refresh(user)
        
    # 3. Генерируем токен
    # Срок действия токена 2 недели (увеличено для удобства WebApp)
    access_token = create_access_token(
        data={"user_id": user.tg_id}, 
        expires_delta=timedelta(weeks=2)
    )
    return {"access_token": access_token, "token_type": "bearer"}
