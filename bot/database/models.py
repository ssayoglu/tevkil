from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    BigInteger, Integer, Float, String, Text, Boolean, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from bot.database.connection import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram User ID
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Kısıtlama / Kara liste
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    banned_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ban_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Rank ve Ceza Puanı Sistemi
    rank_score: Mapped[int] = mapped_column(Integer, default=100)  # Başlangıç: 100
    penalty_points: Mapped[int] = mapped_column(Integer, default=0)
    completed_tevkils_count: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_tevkils_count: Mapped[int] = mapped_column(Integer, default=0)

    # Baro Levha Doğrulama
    baro_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    baro_sicil_no: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tbb_sicil_no: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_baro_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    baro_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    baro_verification_status: Mapped[str] = mapped_column(String(32), default="NONE")  # NONE, PENDING, VERIFIED, REJECTED
    baro_document_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    listings: Mapped[List["Listing"]] = relationship("Listing", back_populates="creator")
    applications: Mapped[List["Application"]] = relationship("Application", back_populates="user")
    penalty_logs: Mapped[List["PenaltyLog"]] = relationship("PenaltyLog", back_populates="user")


class PenaltyLog(Base):
    __tablename__ = "penalty_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    issued_by: Mapped[str] = mapped_column(String(64), default="SYSTEM")  # SYSTEM veya ADMIN_<id>
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="penalty_logs")


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message_id: Mapped[int] = mapped_column(Integer)  # İlan sahibinin orijinal mesajı
    bot_reply_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Butonlu bot mesajı
    creator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    
    # Durumlar: OPEN, MATCHED, COMPLETED, CANCELLED_TIMEOUT, CANCELLED_ADMIN, FAILED_DISAGREEMENT
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    matched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    creator: Mapped["User"] = relationship("User", back_populates="listings")
    applications: Mapped[List["Application"]] = relationship("Application", back_populates="listing", order_by="Application.queue_number")
    sessions: Mapped[List["BridgeSession"]] = relationship("BridgeSession", back_populates="listing")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(Integer, ForeignKey("listings.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    queue_number: Mapped[int] = mapped_column(Integer)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    
    # Rank & Handikap Bilgileri
    score_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_rank_score: Mapped[int] = mapped_column(Integer, default=100)
    handicap_level: Mapped[int] = mapped_column(Integer, default=0)
    
    # Durumlar: WAITING, ACTIVE, ACCEPTED, REJECTED, PASSED
    status: Mapped[str] = mapped_column(String(32), default="WAITING")
    disagreement_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    listing: Mapped["Listing"] = relationship("Listing", back_populates="applications")
    user: Mapped["User"] = relationship("User", back_populates="applications")

    __table_args__ = (
        Index("idx_listing_user", "listing_id", "user_id", unique=True),
    )


class BridgeSession(Base):
    __tablename__ = "bridge_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(Integer, ForeignKey("listings.id"), index=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    applicant_id: Mapped[int] = mapped_column(BigInteger, index=True)
    candidate_rank: Mapped[int] = mapped_column(Integer, default=1)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    creator_first_message_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    first_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    timeout_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    creator_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    applicant_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    listing: Mapped["Listing"] = relationship("Listing", back_populates="sessions")


class MessageLog(Base):
    __tablename__ = "message_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(Integer, ForeignKey("listings.id"), index=True)
    session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sender_id: Mapped[int] = mapped_column(BigInteger)
    sender_role: Mapped[str] = mapped_column(String(32))  # CREATOR, APPLICANT, ADMIN, SYSTEM
    content_type: Mapped[str] = mapped_column(String(32))  # text, photo, document, voice
    text_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
