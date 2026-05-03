from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from .schemas import UserOut
from sqlalchemy.orm import Session
from .db import get_db

router = APIRouter()

class GoogleAuthRequest(BaseModel):
    id_token: str

class AppleAuthRequest(BaseModel):
    id_token: str

class PhoneAuthRequest(BaseModel):
    phone: str
    code: str

@router.post("/auth/google", response_model=UserOut)
def google_login(request: GoogleAuthRequest, db: Session = Depends(get_db)):
    # TODO: Implement Google token verification
    raise HTTPException(status_code=501, detail="Google auth not implemented (no keys)")

@router.post("/auth/apple", response_model=UserOut)
def apple_login(request: AppleAuthRequest, db: Session = Depends(get_db)):
    # TODO: Implement Apple token verification
    raise HTTPException(status_code=501, detail="Apple auth not implemented (no keys)")

@router.post("/auth/phone", response_model=UserOut)
def phone_login(request: PhoneAuthRequest, db: Session = Depends(get_db)):
    # TODO: Implement Phone verification
    raise HTTPException(status_code=501, detail="Phone auth not implemented (no keys)")
