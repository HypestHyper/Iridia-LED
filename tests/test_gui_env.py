"""The window picks GTK's GL renderer unless you chose one."""
from iridia.gui import pick_renderer


def test_gl_unless_chosen():
    env = {}
    pick_renderer(env)
    assert env["GSK_RENDERER"] == "gl"
    env = {"GSK_RENDERER": "vulkan"}
    pick_renderer(env)
    assert env["GSK_RENDERER"] == "vulkan"
