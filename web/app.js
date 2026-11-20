const form = document.querySelector("#composer");
const fields = document.querySelector("#composer-fields");
const publishButton = document.querySelector("#publish");
const results = document.querySelector("#results");
const platformInputs = [...form.querySelectorAll("[name=platforms]")];
const previewButtons = [...document.querySelectorAll("[data-preview]")];
const platformNames = { linkedin: "LinkedIn", bluesky: "Bluesky" };
const lengthError = document.querySelector("#length-error");
const segmenter = typeof Intl.Segmenter === "function" ? new Intl.Segmenter(undefined, { granularity: "grapheme" }) : null;
const encoder = new TextEncoder();
let limits;

function normalizedTags() {
  return form.elements.hashtags.value.split(/\s+/)
    .map(tag => tag.replace(/^#+|#+$/g, ""))
    .filter(Boolean)
    .map(tag => `#${tag}`);
}

function checkLengths(selected) {
  if (!limits) return false;
  const tags = normalizedTags();
  const description = form.elements.description.value.trim();
  const text = [description, ...tags].join(" ");
  const url = form.elements.url.value.trim();
  const errors = [];
  const linkedin = limits.linkedin;
  const bluesky = limits.bluesky;
  const linkedinCount = Array.from(text).length;
  const blueskyBytes = encoder.encode(text).length;
  const blueskyCount = segmenter ? Array.from(segmenter.segment(text)).length : null;
  const linkedinLength = document.querySelector("#linkedin-length");
  const blueskyLength = document.querySelector("#bluesky-length");
  const linkedinOver = linkedinCount > linkedin.text;
  const blueskyOver = blueskyCount > bluesky.text || blueskyBytes > bluesky.text_bytes;

  linkedinLength.textContent = `LinkedIn · ${linkedinCount} / ${linkedin.text} characters`;
  blueskyLength.textContent = blueskyCount === null || blueskyBytes > bluesky.text_bytes
    ? `Bluesky · ${blueskyBytes} / ${bluesky.text_bytes} UTF-8 bytes`
    : `Bluesky · ${blueskyCount} / ${bluesky.text} characters`;
  linkedinLength.classList.toggle("error", linkedinOver);
  blueskyLength.classList.toggle("error", blueskyOver);

  if (selected.includes("linkedin")) {
    if (linkedinOver) errors.push("Shorten the post text or hashtags for LinkedIn.");
    if (Array.from(url).length > linkedin.url) errors.push(`LinkedIn article URLs can contain up to ${linkedin.url} characters.`);
  }
  if (selected.includes("bluesky")) {
    if (blueskyOver) errors.push("Shorten the post text or hashtags for Bluesky.");
    const overlongTag = tags.findIndex(tag => {
      const value = tag.replaceAll("#", "");
      return encoder.encode(value).length > bluesky.tag_bytes
        || (segmenter && Array.from(segmenter.segment(value)).length > bluesky.tag);
    });
    if (overlongTag !== -1) {
      errors.push(`Bluesky hashtag ${overlongTag + 1} exceeds ${bluesky.tag} characters or ${bluesky.tag_bytes} UTF-8 bytes.`);
    }
    if (encoder.encode(url).length > bluesky.url) errors.push(`Bluesky article URLs can contain up to ${bluesky.url} UTF-8 bytes.`);
  }
  const message = errors.join(" ");
  if (lengthError.textContent !== message) lengthError.textContent = message;
  lengthError.hidden = !message;
  return errors.length > 0;
}

function updatePublishButton() {
  const selected = platformInputs.filter(input => input.checked && !input.disabled).map(input => input.value);
  const overLimit = checkLengths(selected);
  publishButton.disabled = fields.disabled || selected.length === 0 || overLimit;
}

function updatePreview() {
  const description = form.elements.description.value.trim();
  const previewDescription = document.querySelector("#preview-description");
  previewDescription.textContent = description || "Your post text will appear here.";
  previewDescription.classList.toggle("placeholder", !description);

  const tags = normalizedTags();
  const previewTags = document.querySelector("#preview-tags");
  previewTags.textContent = tags.join(" ");
  previewTags.hidden = tags.length === 0;

  document.querySelector("#preview-title").textContent = form.elements.title.value.trim() || "Article title";
  let hostname = "";
  try {
    const article = new URL(form.elements.url.value);
    if (["http:", "https:"].includes(article.protocol)) hostname = article.hostname;
  } catch {
    // Keep the placeholder while the URL is incomplete.
  }
  document.querySelector("#preview-url").textContent = hostname || "example.com";
}

function showResult(message, kind) {
  const line = document.createElement("p");
  line.textContent = message;
  if (kind) line.classList.add(kind);
  results.append(line);
}

async function loadPlatforms() {
  try {
    const response = await fetch("/api/platforms");
    if (!response.ok) throw new Error();
    const configured = await response.json();
    limits = configured.limits;
    document.querySelector("#post-lengths").hidden = !limits;
    for (const input of platformInputs) {
      const available = configured[input.value] === true;
      input.disabled = !available;
      input.checked = available;
      document.querySelector(`#${input.value}-state`).textContent = available ? "Configured" : "Setup needed";
    }
    document.querySelector("#configuration-help").hidden = platformInputs.every(input => !input.disabled);
    updatePublishButton();
  } catch {
    for (const input of platformInputs) {
      document.querySelector(`#${input.value}-state`).textContent = "Unavailable";
    }
    showResult("Could not load platforms. Refresh the page to try again.", "error");
  }
}

form.addEventListener("input", () => {
  updatePreview();
  updatePublishButton();
});

for (const button of previewButtons) {
  button.addEventListener("click", () => {
    const platform = button.dataset.preview;
    for (const option of previewButtons) option.setAttribute("aria-pressed", option === button);
    const mark = document.querySelector("#preview-mark");
    mark.className = `platform-mark ${platform}`;
    mark.textContent = platform === "linkedin" ? "in" : "b";
    document.querySelector("#preview-platform").textContent = platformNames[platform];
  });
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (publishButton.disabled) return;
  const data = new FormData(form);
  const payload = {
    description: data.get("description"),
    hashtags: data.get("hashtags"),
    url: data.get("url"),
    title: data.get("title"),
    platforms: data.getAll("platforms"),
  };

  fields.disabled = true;
  publishButton.textContent = "Publishing…";
  updatePublishButton();
  results.replaceChildren();
  showResult("Publishing your post…");
  try {
    const response = await fetch("/api/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    results.replaceChildren();
    if (!response.ok) {
      showResult(data.error, "error");
      return;
    }
    for (const input of platformInputs) {
      const result = data.results[input.value];
      if (!result) continue;
      showResult(`${platformNames[input.value]} · ${result.message}`, result.ok ? "success" : "error");
      if (result.ok) input.checked = false;
    }
  } catch {
    results.replaceChildren();
    showResult("Could not confirm publishing. Check your accounts before trying again.", "error");
  } finally {
    fields.disabled = false;
    publishButton.textContent = "Publish post";
    updatePublishButton();
  }
});

updatePreview();
loadPlatforms();
