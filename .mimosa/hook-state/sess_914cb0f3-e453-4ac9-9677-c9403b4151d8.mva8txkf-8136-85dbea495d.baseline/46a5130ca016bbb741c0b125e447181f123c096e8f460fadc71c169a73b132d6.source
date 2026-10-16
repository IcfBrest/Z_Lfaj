from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from ..db import get_db
from ..models import BackgroundTask, Resume, User, utcnow
from ..parsers import extract_identity, mask_text, parse_resume_profile
from ..resume_extract import extract_text
from ..security import encrypt_text
from ..task_runner import enqueue, run_with_status
from .deps import get_current_user

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

ALLOWED = {"pdf": ".pdf", "docx": ".docx", "md": ".md"}


def run_resume_parse(task_id: str, SessionLocal_: sessionmaker) -> None:
    def work(db: Session) -> None:
        task = db.get(BackgroundTask, task_id)
        if task is None or task.ref_id is None:
            raise RuntimeError("任务引用缺失")
        resume = db.get(Resume, task.ref_id)
        if resume is None:
            raise RuntimeError("简历不存在")

        from ..security import decrypt_text

        original = decrypt_text(resume.original_encrypted)
        identity = extract_identity(db, task.user_id, original)
        masked = mask_text(original, identity)
        profile = parse_resume_profile(db, task.user_id, masked)
        resume.parsed_profile_json = profile
        resume.parse_status = "done"
        resume.parse_error = None
        db.commit()

    run_with_status(task_id, SessionLocal_, work)


def _fail(db: Session, resume_id: int, message: str) -> None:
    resume = db.get(Resume, resume_id)
    if resume is not None:
        resume.parse_status = "failed"
        resume.parse_error = message
        db.commit()


@router.post("", status_code=202)
async def upload_resume(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    file_format = next((fmt for fmt, ext in ALLOWED.items() if ext == suffix), None)
    if file_format is None:
        raise HTTPException(400, f"不支持的文件类型 {suffix or '(无后缀)'}，仅支持 PDF/DOCX/MD")

    data = await file.read()
    if len(data) > settings.upload_max_bytes:
        raise HTTPException(400, "文件超过大小限制（10MB）")

    # 本地抽取：抽取失败立即报错，不创建记录
    text = extract_text(data, file_format)

    # 版本号 = 同名简历的历史数 + 1；同用户首份简历默认 master
    same_name = db.query(Resume).filter_by(user_id=user.id, name=file.filename).count()
    has_master = db.query(Resume.id).filter_by(user_id=user.id, is_master=True).first() is not None

    resume = Resume(
        user_id=user.id,
        name=file.filename,
        file_path=f"data/uploads/{user.id}/{file.filename}",
        file_format=file_format,
        original_encrypted=encrypt_text(text),
        version=same_name + 1,
        is_master=not has_master,
        parse_status="pending",
    )
    db.add(resume)
    db.flush()

    upload_dir = Path("data/uploads") / str(user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / file.filename).write_bytes(data)

    db.commit()
    task_id = enqueue(background_tasks, db, "resume_parse", user.id, run_resume_parse, "resume", resume.id)
    return {"resume_id": resume.id, "task_id": task_id, "version": resume.version, "is_master": resume.is_master}


@router.get("")
def list_resumes(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    items = db.query(Resume).filter_by(user_id=user.id).order_by(Resume.id.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "file_format": r.file_format,
            "version": r.version,
            "is_master": r.is_master,
            "parse_status": r.parse_status,
            "parse_error": r.parse_error,
            "created_at": r.created_at.isoformat(),
        }
        for r in items
    ]


@router.get("/{resume_id}")
def get_resume(resume_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    resume = db.query(Resume).filter_by(id=resume_id, user_id=user.id).one_or_none()
    if resume is None:
        raise HTTPException(404, "简历不存在")
    return {
        "id": resume.id,
        "name": resume.name,
        "file_format": resume.file_format,
        "version": resume.version,
        "is_master": resume.is_master,
        "parse_status": resume.parse_status,
        "parse_error": resume.parse_error,
        "parsed_profile": resume.parsed_profile_json,
        "created_at": resume.created_at.isoformat(),
    }


@router.post("/{resume_id}/set-master", status_code=204)
def set_master(resume_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    resume = db.query(Resume).filter_by(id=resume_id, user_id=user.id).one_or_none()
    if resume is None:
        raise HTTPException(404, "简历不存在")
    db.query(Resume).filter(Resume.user_id == user.id).update({"is_master": False})
    resume.is_master = True
    db.commit()


@router.delete("/{resume_id}", status_code=204)
def delete_resume(resume_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    resume = db.query(Resume).filter_by(id=resume_id, user_id=user.id).one_or_none()
    if resume is None:
        raise HTTPException(404, "简历不存在")
    db.delete(resume)
    db.commit()
