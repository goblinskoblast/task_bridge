import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AI_PROVIDER", "openai")

from bot.task_file_binding import extract_task_reference, resolve_task_for_file_upload


def make_task(task_id: int, title: str, updated_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=task_id,
        title=title,
        updated_at=updated_at,
        created_at=updated_at,
    )


class FileUploadBindingTest(unittest.TestCase):
    def test_extract_task_reference_supports_supported_formats(self):
        self.assertEqual(extract_task_reference("#task123"), 123)
        self.assertEqual(extract_task_reference("task: 77"), 77)
        self.assertEqual(extract_task_reference("задача 45"), 45)
        self.assertIsNone(extract_task_reference("без ссылки"))

    @patch("bot.task_file_binding.get_user_in_progress_tasks")
    def test_resolve_task_uses_explicit_reference(self, mocked_get_tasks):
        mocked_get_tasks.return_value = [
            make_task(5, "Подготовить отчет", datetime.now()),
            make_task(9, "Сверить стоп-лист", datetime.now() - timedelta(hours=1)),
        ]

        task, error = resolve_task_for_file_upload(db=object(), user_id=1, caption="Файл по #task9")

        self.assertIsNone(error)
        self.assertIsNotNone(task)
        self.assertEqual(task.id, 9)

    @patch("bot.task_file_binding.get_user_in_progress_tasks")
    def test_resolve_task_requires_reference_when_multiple_tasks_exist(self, mocked_get_tasks):
        mocked_get_tasks.return_value = [
            make_task(5, "Подготовить отчет", datetime.now()),
            make_task(9, "Сверить стоп-лист", datetime.now() - timedelta(hours=1)),
        ]

        task, error = resolve_task_for_file_upload(db=object(), user_id=1, caption="Отчет готов")

        self.assertIsNone(task)
        self.assertIsNotNone(error)
        self.assertIn("#5 Подготовить отчет", error)
        self.assertIn("#9 Сверить стоп-лист", error)

    @patch("bot.task_file_binding.get_user_in_progress_tasks")
    def test_resolve_task_rejects_unknown_reference(self, mocked_get_tasks):
        mocked_get_tasks.return_value = [
            make_task(5, "Подготовить отчет", datetime.now()),
        ]

        task, error = resolve_task_for_file_upload(db=object(), user_id=1, caption="#task99")

        self.assertIsNone(task)
        self.assertIsNotNone(error)
        self.assertIn("Задача #99 не найдена", error)


if __name__ == "__main__":
    unittest.main()
