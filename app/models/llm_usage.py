from sqlalchemy import Column, DateTime, Integer, Numeric, String, func

from app.database import Base


class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model = Column(String(100), nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    estimated_cost_usd = Column(Numeric(10, 6), nullable=False)
    # Nullable tag identifying the triggering context (e.g. "auto_ingest").
    # Lets us enforce a separate budget cap for autonomous work.
    source = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
