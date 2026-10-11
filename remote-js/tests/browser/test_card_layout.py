"""Layout of the canonical video card: the download buttons fit the card.

The card list has 1, 2, or 3 columns, so a card can be narrow on a wide
window. The download buttons must not overlap, and their labels must stay in
the button, at each window width.
"""

import unittest

from base import BrowserTestCase, new_project, project_url, seed_card

# The window widths to check: phone, tablet, and the 2- and 3-column lists.
WIDTHS = (360, 640, 860, 1024, 1280, 1600)

CHECK_DOWNLOADS = """
(group) => {
  const buttons = [...group.querySelectorAll('[data-slot=button]')];
  const problems = [];
  const boxes = buttons.map((b) => b.getBoundingClientRect());
  buttons.forEach((b, i) => {
    if (b.scrollWidth > b.clientWidth + 1) problems.push(`label overflows button ${i}`);
    for (const child of b.querySelectorAll('span')) {
      const c = child.getBoundingClientRect();
      if (c.right > boxes[i].right + 1 || c.left < boxes[i].left - 1) {
        problems.push(`text outside button ${i}: ${child.textContent}`);
      }
    }
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], c = boxes[j];
      const overlap = a.left < c.right - 1 && c.left < a.right - 1 && a.top < c.bottom - 1 && c.top < a.bottom - 1;
      if (overlap) problems.push(`button ${i} overlaps button ${j}`);
    }
  });
  return problems;
}
"""


class CardLayoutTest(BrowserTestCase):
    def test_download_buttons_fit_the_card_at_each_width(self):
        project = new_project("layout")
        title = "الإعلان عن افتتاح الموسم السابع لبرنامج إعداد طالب علم مميز في مركزنا مركز إحياء علوم الدين"
        for i in range(3):
            seed_card(project, f"2026-10-06 06-58-0{i}-vertical-no-overlay", title)
        for width in WIDTHS:
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 900})
                self.page.goto(project_url(project, "/videos#admin"))
                groups = self.page.get_by_role("group", name=f"Downloads for {title}")
                groups.first.wait_for()
                for index in range(groups.count()):
                    problems = groups.nth(index).evaluate(CHECK_DOWNLOADS)
                    self.assertEqual(problems, [], f"width {width}, card {index}")


if __name__ == "__main__":
    unittest.main()
