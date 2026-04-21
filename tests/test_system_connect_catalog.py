import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from db.models import Base, DataAgentSystem
from data_agent.models import SystemConnectRequest
from data_agent.service import DataAgentService


class SystemConnectCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = Path(path)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.service = DataAgentService()

    def tearDown(self) -> None:
        self.engine.dispose()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_connect_system_detects_iiko_and_exposes_catalog_metadata(self):
        payload = SystemConnectRequest(
            user_id=137236883,
            url="https://sso.iiko.biz/auth",
            username="priority",
            password="secret",
        )

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.service.encrypt_password", return_value="encrypted-secret"):
                response = asyncio.run(self.service.connect_system(payload))

        self.assertTrue(response.success)
        self.assertIsNotNone(response.system)
        self.assertEqual(response.system.system_name, "iiko")
        self.assertEqual(response.system.system_family, "restaurant_operations")
        self.assertTrue(response.system.supports_scan)
        self.assertTrue(response.system.supports_points)
        self.assertIn("точки", response.system.capability_labels)
        self.assertIn("организация", response.system.orientation_summary or "")
        self.assertIn("scan структуры iiko", response.system.next_step_hint or "")
        self.assertIsNotNone(response.system.scan_contract)
        self.assertEqual(response.system.scan_contract.stage, "scaffold")
        self.assertEqual(response.system.scan_contract.auth_mode, "sso_web")
        self.assertIn("организация", response.system.scan_contract.primary_entities)
        self.assertIn("доступность", response.system.scan_contract.monitor_signals)
        self.assertEqual(response.system.scan_contract.starter_step, "Войти и подтвердить контур организации")
        self.assertTrue(response.system.scan_contract.scan_steps)
        self.assertTrue(response.system.scan_contract.capability_matrix)
        self.assertIsNotNone(response.system.scan_progress)
        self.assertEqual(response.system.scan_progress.status, "not_started")
        self.assertEqual(response.system.scan_progress.status_label, "ещё не начинали")
        self.assertEqual(response.system.scan_progress.next_step_id, "login")
        self.assertEqual(response.system.scan_progress.next_step_label, "Войти и подтвердить контур организации")

        session = self.SessionLocal()
        try:
            item = session.query(DataAgentSystem).first()
        finally:
            session.close()

        self.assertIsNotNone(item)
        self.assertEqual(item.system_name, "iiko")
        self.assertEqual((item.metadata_json or {}).get("catalog_family"), "restaurant_operations")
        self.assertEqual((item.metadata_json or {}).get("scan_progress", {}).get("status"), "not_started")
        self.assertEqual(
            (item.metadata_json or {}).get("scan_progress", {}).get("next_step_label"),
            "Войти и подтвердить контур организации",
        )

    def test_connect_system_detects_keeper(self):
        payload = SystemConnectRequest(
            user_id=137236883,
            url="https://cloud.rkeeper.com/dashboard",
            username="priority",
            password="secret",
        )

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.service.encrypt_password", return_value="encrypted-secret"):
                response = asyncio.run(self.service.connect_system(payload))

        self.assertTrue(response.success)
        self.assertIsNotNone(response.system)
        self.assertEqual(response.system.system_name, "keeper")
        self.assertEqual(response.system.system_title, "Keeper")
        self.assertTrue(response.system.supports_monitoring)
        self.assertIn("объект", response.system.orientation_summary or "")
        self.assertEqual(response.system.scan_contract.stage, "scaffold")
        self.assertEqual(response.system.scan_contract.auth_mode, "web_login")
        self.assertEqual(response.system.scan_contract.starter_step, "Войти и открыть рабочий объект")
        self.assertEqual(response.system.scan_progress.status_label, "ещё не начинали")
        self.assertEqual(response.system.scan_progress.next_step_label, "Войти и открыть рабочий объект")

    def test_reconnect_system_preserves_existing_scan_progress(self):
        payload = SystemConnectRequest(
            user_id=137236883,
            url="https://sso.iiko.biz/auth",
            username="priority",
            password="secret",
        )

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.service.encrypt_password", return_value="encrypted-secret"):
                first_response = asyncio.run(self.service.connect_system(payload))

        self.assertTrue(first_response.success)

        session = self.SessionLocal()
        try:
            item = session.query(DataAgentSystem).first()
            metadata = dict(item.metadata_json or {})
            metadata["scan_progress"] = {
                "status": "in_progress",
                "current_step_id": "map_organizations",
                "current_step_label": "Снять карту организаций и точек",
                "next_step_id": "map_organizations",
                "next_step_label": "Снять карту организаций и точек",
                "discovered_entities": ["организация"],
                "discovered_sections": ["организации"],
                "evidence_summary": "после входа виден список организаций",
            }
            item.metadata_json = metadata
            session.commit()
        finally:
            session.close()

        with patch("data_agent.service.get_db_session", side_effect=self.SessionLocal):
            with patch("data_agent.service.encrypt_password", return_value="encrypted-secret-2"):
                second_response = asyncio.run(self.service.connect_system(payload))

        self.assertTrue(second_response.success)
        self.assertEqual(second_response.system.scan_progress.status, "in_progress")
        self.assertEqual(second_response.system.scan_progress.status_label, "идёт scan")
        self.assertEqual(second_response.system.scan_progress.current_step_id, "map_organizations")
        self.assertEqual(second_response.system.scan_progress.current_step_label, "Снять карту организаций и точек")
        self.assertEqual(second_response.system.scan_progress.discovered_entities, ["организация"])


if __name__ == "__main__":
    unittest.main()
