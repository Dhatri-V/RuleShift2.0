"""Original PDF bytes and parser output, owned by one policy version."""
from sqlalchemy import (CheckConstraint, Column, DDL, ForeignKey, ForeignKeyConstraint,
                        Integer, LargeBinary, String, Text, event)
from sqlalchemy.orm import relationship
from database.db import Base


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        ForeignKeyConstraint(["policy_id", "version_id"],
                             ["policy_versions.family_id", "policy_versions.id"],
                             ondelete="RESTRICT", name="fk_source_version_owner"),
        CheckConstraint("length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_source_sha256"),
        CheckConstraint("byte_count > 0 AND length(pdf_bytes) = byte_count", name="ck_source_bytes"),
        CheckConstraint("page_count > 0", name="ck_source_pages"),
    )
    version_id = Column(Integer, primary_key=True, autoincrement=False)
    policy_id = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    pdf_bytes = Column(LargeBinary, nullable=False)
    byte_count = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=False)
    parser = Column(String, nullable=False)
    version = relationship("PolicyVersion", back_populates="source_document")
    pages = relationship("SourcePage", back_populates="document", passive_deletes="all")


class SourcePage(Base):
    __tablename__ = "source_pages"
    __table_args__ = (CheckConstraint("page_number >= 1", name="ck_source_page_number"),)
    version_id = Column(Integer, ForeignKey("source_documents.version_id", ondelete="RESTRICT"), primary_key=True)
    page_number = Column(Integer, primary_key=True)
    source_text = Column(Text, nullable=False)
    document = relationship("SourceDocument", back_populates="pages")


# New versions receive new records; existing source bytes/text cannot be edited
# or replaced. Draft deletion may explicitly remove the complete owned source.
for model, key in ((SourceDocument, "version_id = NEW.version_id"),
                   (SourcePage, "version_id = NEW.version_id AND page_number = NEW.page_number")):
    table = model.__tablename__
    for suffix, action, condition in (
        ("update", "UPDATE", ""),
        ("replace", "INSERT", f"WHEN EXISTS (SELECT 1 FROM {table} WHERE {key}) "),
    ):
        event.listen(model.__table__, "after_create", DDL(
            f"CREATE TRIGGER {table}_no_{suffix} BEFORE {action} ON {table} "
            f"{condition}BEGIN SELECT RAISE(ABORT, 'source evidence is immutable'); END"
        ).execute_if(dialect="sqlite"))
