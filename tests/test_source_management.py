from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import modules.source_manager as source_module
from modules.source_manager import DataSourceConfig, load_sources, run_collection_job, save_sources


class SourceManagementTests(unittest.TestCase):
    @patch("modules.source_manager.build_project_index")
    @patch("modules.source_manager.collect_source")
    @patch("modules.source_manager.save_sources")
    @patch("modules.source_manager.load_sources")
    def test_force_collection_still_skips_disabled_sources(self, load, save, collect, _build):
        load.return_value = [DataSourceConfig(source_id="sample", source_type="csv", enabled=False)]

        result = run_collection_job(force=True, use_llm_filter=False)

        collect.assert_not_called()
        save.assert_called_once()
        self.assertEqual(result["collected"], [])

    def test_runtime_source_store_survives_fresh_reload_and_delete(self):
        with TemporaryDirectory() as temp_dir:
            runtime_path = Path(temp_dir) / "sources.runtime.json"
            yaml_path = Path(temp_dir) / "sources.yaml"
            yaml_path.write_text("sources: []\n", encoding="utf-8")
            old_runtime = source_module.SOURCE_CONFIG_PATH
            old_yaml = source_module.SCENARIO_SOURCE_YAML
            try:
                source_module.SOURCE_CONFIG_PATH = runtime_path
                source_module.SCENARIO_SOURCE_YAML = yaml_path
                source = DataSourceConfig(source_id="persisted", source_type="rss", url="https://www.agri.cn/rss")
                source.mark_run()
                save_sources([source])

                reloaded = load_sources()
                source_module.delete_source("persisted")
                after_delete = load_sources()
            finally:
                source_module.SOURCE_CONFIG_PATH = old_runtime
                source_module.SCENARIO_SOURCE_YAML = old_yaml

        self.assertEqual(reloaded[0].source_id, "persisted")
        self.assertTrue(reloaded[0].last_run_at)
        self.assertEqual(after_delete, [])


if __name__ == "__main__":
    unittest.main()
