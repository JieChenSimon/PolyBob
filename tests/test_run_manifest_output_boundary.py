from libs.data.run_manifest import _is_code


def test_dashboard_visual_outputs_do_not_make_research_code_dirty():
    assert _is_code("apps/dashboard/components/Chart.tsx") is True
    assert _is_code("apps/dashboard/output/playwright/home.png") is False
    assert _is_code("apps/dashboard/.next/build-manifest.json") is False
