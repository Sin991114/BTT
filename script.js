// BTT Practice – single-question flow with 4 options
// Loads data from questions.json and answers.json (same directory)

(function () {
  const dataVersion = Date.now();
  const els = {
    status: document.getElementById('status'),
    qid: document.getElementById('qid'),
    media: document.getElementById('media'),
    question: document.getElementById('question'),
    options: document.getElementById('options'),
    next: document.getElementById('nextBtn'),
    scoreText: document.getElementById('scoreText'),
    progressText: document.getElementById('progressText'),
    progressBar: document.getElementById('progressBar'),
  };

  /** In-memory dataset of { id, question, options[4], answerIndex } */
  let dataset = [];
  let currentIndex = -1;
  let attempts = 0;
  let correct = 0;

  function setStatus(msg) {
    els.status.textContent = msg || '';
  }

  function shuffle(arr) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  function pickNextIndex() {
    if (!dataset.length) return -1;
    return Math.floor(Math.random() * dataset.length);
  }

  function renderQuestion(item) {
    const displayNum = attempts + 1;
    els.question.textContent = `Q${displayNum}. ${item.question}`;
    if (els.qid) els.qid.textContent = `Source ID: ${item.id}`;
    els.media.innerHTML = '';
    els.options.innerHTML = '';
    els.next.disabled = true;

    // Render image(s) if present
    const imgs = [];
    if (item.image && typeof item.image === 'string') imgs.push(item.image);
    if (Array.isArray(item.images)) imgs.push(...item.images);
    for (const src of imgs) {
      const img = document.createElement('img');
      img.loading = 'lazy';
      img.alt = 'Question image';
      img.onerror = () => {
        // Treat as no image: remove broken element silently
        if (img.parentNode) img.parentNode.removeChild(img);
      };
      img.src = src + `?v=${dataVersion}`;
      els.media.appendChild(img);
    }
    // If none successfully load, keep media empty
    setTimeout(() => {
      if (!els.media.querySelector('img')) els.media.innerHTML = '';
    }, 0);

    // Build option buttons
    item.options.forEach((text, i) => {
      const btn = document.createElement('button');
      btn.className = 'option';
      btn.type = 'button';

      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = String.fromCharCode(65 + i); // A/B/C/D
      const label = document.createElement('span');
      label.textContent = text;
      btn.appendChild(badge);
      btn.appendChild(label);

      btn.addEventListener('click', () => onSelect(i));
      els.options.appendChild(btn);
    });

    function onSelect(selectedIdx) {
      // lock further selections
      const optionEls = Array.from(els.options.children);
      optionEls.forEach((b) => (b.disabled = true));

      const correctIdx = item.answerIndex;
      optionEls[correctIdx]?.classList.add('correct');
      if (selectedIdx !== correctIdx) {
        optionEls[selectedIdx]?.classList.add('wrong');
        setStatus('Incorrect. Correct answer highlighted.');
      } else {
        setStatus('Correct!');
      }
      attempts += 1;
      if (selectedIdx === correctIdx) correct += 1;
      updateStats();
      els.next.disabled = false;
    }
  }

  function nextQuestion() {
    currentIndex = pickNextIndex();
    if (currentIndex === -1) {
      setStatus('No questions available.');
      els.question.textContent = '';
      els.options.innerHTML = '';
      els.next.disabled = true;
      return;
    }
    setStatus('');
    renderQuestion(dataset[currentIndex]);
  }

  function updateStats() {
    const total = dataset.length || 0;
    const pct = attempts ? Math.round((correct / attempts) * 100) : 0;
    els.scoreText.textContent = `Score: ${correct}/${attempts} (${pct}%)`;
    els.progressText.textContent = `Progress: ${attempts}/${total}`;
    const width = total ? Math.min(100, Math.round((attempts / total) * 100)) : 0;
    if (els.progressBar) els.progressBar.style.width = `${width}%`;
  }

  async function loadData() {
    // Attempt to fetch both files. Provide graceful fallbacks and helpful errors.
    try {
      const bust = `?v=${dataVersion}`;
      const [qRes, aRes] = await Promise.all([
        fetch('questions.json' + bust),
        fetch('answers.json' + bust),
      ]);

      if (!qRes.ok) throw new Error('questions.json not found');
      if (!aRes.ok) throw new Error('answers.json not found');

      const questions = await qRes.json();
      const answersRaw = await aRes.json();

      // Normalize answers: support array form [2,1,3,...] or object map {"1":2,...}
      const answerIndexById = new Map();
      if (Array.isArray(answersRaw)) {
        // Assume positional: index matches questions order; value is correct option index
        answersRaw.forEach((ansIdx, i) => answerIndexById.set(questions[i]?.id ?? i + 1, ansIdx));
      } else if (answersRaw && typeof answersRaw === 'object') {
        Object.keys(answersRaw).forEach((k) => {
          const id = isNaN(+k) ? k : +k;
          answerIndexById.set(id, answersRaw[k]);
        });
      }

      // Build dataset and keep only valid questions (3 or 4 options)
      const merged = [];
      for (const q of questions) {
        const opts = q.options || q.choices || q.answers;
        if (!opts || opts.length < 3) continue;
        const id = q.id ?? merged.length + 1;
        let ans = answerIndexById.has(id) ? answerIndexById.get(id) : undefined;

        // Also support if question carries answerIndex directly
        if (ans === undefined && typeof q.answerIndex === 'number') ans = q.answerIndex;
        const optionsCount = Math.min(4, opts.length);
        if (typeof ans !== 'number' || ans < 0 || ans >= optionsCount) continue;

        const out = { id, question: q.question || q.text || '', options: opts.slice(0, optionsCount), answerIndex: ans };
        if (Array.isArray(q.images)) out.images = q.images;
        else if (typeof q.image === 'string') out.images = [q.image];
        merged.push(out);
      }

      if (!merged.length) throw new Error('No valid questions after merging');
      dataset = shuffle(merged);
      updateStats();
      nextQuestion();
    } catch (err) {
      console.error(err);
      setStatus(
        'Could not load data. Add questions.json and answers.json, or keep sample files.'
      );
      // Fallback to a tiny sample so UI is testable
      dataset = [
        {
          id: 1,
          question: 'At a zebra crossing without traffic lights, you should…',
          options: [
            'Speed up and pass before pedestrians step on the road.',
            'Slow down, be prepared to stop, and give way to pedestrians.',
            'Sound your horn to warn pedestrians not to cross.',
            'Ignore pedestrians if you have right of way.',
          ],
          answerIndex: 1,
        },
        {
          id: 2,
          question: 'When the traffic light turns amber, you should…',
          options: [
            'Accelerate to beat the red light.',
            'Stop if you can do so safely before the stop line.',
            'Proceed without caution as it is not red.',
            'Sound the horn and continue driving.',
          ],
          answerIndex: 1,
        },
      ];
      updateStats();
      nextQuestion();
    }
  }

  els.next.addEventListener('click', () => nextQuestion());

  loadData();
})();
