// Small progressive enhancements. Pages work without JavaScript except kanban drag-and-drop.

window.initBoard = function () {
  if (!window.Sortable) return;
  const lists = document.querySelectorAll(".kanban-list");
  const errorBox = document.getElementById("board-error");
  let lastMove = null;
  lists.forEach((list) => {
    Sortable.create(list, {
      group: "board",
      animation: 120,
      onAdd: (evt) => {
        const card = evt.item;
        const jobId = card.dataset.jobId;
        const status = evt.to.dataset.status;
        lastMove = evt;
        htmx.ajax("POST", `/jobs/${jobId}/status`, {
          target: `#card-${jobId}`,
          swap: "outerHTML",
          values: { status: status },
        }).then(() => updateCounts()).catch(() => revert(evt));
      },
    });
  });

  document.body.addEventListener("htmx:responseError", (evt) => {
    // htmx does not swap 4xx/5xx responses, so put the card back where it came from.
    if (lastMove && evt.detail.target && evt.detail.target.classList.contains("kcard")) {
      revert(lastMove);
      lastMove = null;
    }
  });

  function revert(evt) {
    evt.from.insertBefore(evt.item, evt.from.children[evt.oldIndex] || null);
    errorBox.hidden = false;
    updateCounts();
  }

  function updateCounts() {
    lists.forEach((list) => {
      const counter = list.parentElement.querySelector("h2 .muted");
      if (counter) counter.textContent = list.children.length;
    });
  }
};

// Apply page: drag skills between the "Skills" and "Exposure" boxes. Dropping rewrites each
// chip's hidden order and box fields, so the normal Save stores it (no JS: edit them directly).
window.initSkillBoxes = function () {
  const boxes = document.querySelectorAll(".skill-drop");
  if (!window.Sortable || !boxes.length) return;
  const renumber = () => {
    let n = 1;
    boxes.forEach((box) => {
      box.querySelectorAll(".skill").forEach((chip) => {
        chip.querySelector(".pos").value = n++;
        chip.querySelector(".group-select").value = box.dataset.group;
      });
    });
  };
  boxes.forEach((box) => {
    box.closest(".skill-boxes").classList.add("skills-sortable");
    Sortable.create(box, { group: "skills", animation: 120, filter: "input, select, label", preventOnFilter: false, onEnd: renumber });
  });
};

document.addEventListener("DOMContentLoaded", () => {
  if (document.querySelector(".kanban-list")) window.initBoard();
  window.initSkillBoxes();
});

// Settings > target position: "+ Another place" clones the last rule row with fresh indexes.
document.addEventListener("click", (evt) => {
  if (evt.target.id !== "add-rule") return;
  const rows = document.querySelectorAll("#rules .rule");
  const last = rows[rows.length - 1];
  const next = last.cloneNode(true);
  next.querySelectorAll("input, select").forEach((el) => {
    el.name = el.name.replace(/^rules-\d+-/, `rules-${rows.length}-`);
    if (el.type === "checkbox") el.checked = false;
    else el.value = "";
  });
  next.querySelectorAll(".field-error").forEach((el) => el.remove());
  last.after(next);
});

// Master resume: "+ Another …" clones the last row of a section with fresh indexes.
document.addEventListener("click", (evt) => {
  const section = evt.target.dataset && evt.target.dataset.addRow;
  if (!section) return;
  const rows = document.querySelectorAll(`[data-row="${section}"]`);
  const last = rows[rows.length - 1];
  const next = last.cloneNode(true);
  const re = new RegExp(`^${section}-\\d+-`);
  next.querySelectorAll("input, textarea, select").forEach((el) => {
    el.name = el.name.replace(re, `${section}-${rows.length}-`);
    el.value = "";
  });
  next.querySelectorAll(".field-error").forEach((el) => el.remove());
  last.after(next);
});
