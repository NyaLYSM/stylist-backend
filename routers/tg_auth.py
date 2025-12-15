# stylist-backend/routers/tg_auth.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import timedelta

from database import get_db
from models import User 
from schemas import Token 
from utils.auth import create_access_token
# validate_init_data теперь возвращает Tuple[int, Dict]
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
    validation_result = validate_init_data(init_data)
    
    if not validation_result:
        raise HTTPException(
            status_code=401, 
            detail="Недействительные или скомпрометированные данные Telegram (initData)"
        )
        
    tg_user_id, tg_user_data = validation_result # Распаковываем результат

    # 2. Находим или создаем пользователя
    user = db.query(User).filter(User.tg_id == tg_user_id).first()
    
    if not user:
        # Если пользователя нет, создаем его с данными из Telegram
        print(f"Creating new user with tg_id: {tg_user_id}")
        new_user = User(
            tg_id=tg_user_id,
            # Сохраняем имя и юзернейм при создании
            first_name=tg_user_data.get('first_name'),
            last_name=tg_user_data.get('last_name'),
            username=tg_user_data.get('username')
        ) 
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        user = new_user
    else:
        # Опционально: Обновляем имя и юзернейм при каждом входе
        # Это гарантирует, что профиль пользователя актуален
        user.first_name = tg_user_data.get('first_name')
        user.last_name = tg_user_data.get('last_name')
        user.username = tg_user_data.get('username')
        db.commit()
        db.refresh(user)


    # 3. Генерация токена
    access_token_expires = timedelta(minutes=60 * 24 * 7) # Токен на 7 дней
    access_token = create_access_token(
        data={"sub": str(user.tg_id)}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}
