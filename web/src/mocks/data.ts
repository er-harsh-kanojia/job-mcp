// Sample data from Main.dc.html, reshaped to the API contract types. Mock mode only.
import type { Application, AppStatus, DemandRow, Issue, Job, PlanItem, Platform, Profile, Question, ResumeSection, Round, ScoreKey, Severity } from '../api/types';

const URL_BASE: Record<Platform, string> = {
  naukri: 'https://www.naukri.com/job-listings-',
  instahyre: 'https://www.instahyre.com/job-',
  hirist: 'https://www.hirist.tech/j/',
};

type Raw = [string, string, string, Platform, string, string, [number, number], number, boolean, number, number, string[], string, boolean?];
const RAW: Raw[] = [
  ['j1', 'Senior ML Engineer', 'Fractal Analytics', 'naukri', 'Bengaluru', '22–32 LPA', [4, 7], 0, true, 0.92, 0.89, ['Python', 'PyTorch', 'MLOps', 'AWS', 'LLM'], 'Own model training and deployment for retail demand forecasting, and ship to production on AWS with MLflow and SageMaker.'],
  ['j2', 'GenAI Engineer', 'Sarvam AI', 'instahyre', 'Bengaluru', '28–40 LPA', [3, 6], 0, true, 0.88, 0.87, ['LLM', 'RAG', 'LangChain', 'Python', 'Kubernetes'], 'Build retrieval and evaluation pipelines for Indic-language LLM products used by enterprise customers.'],
  ['j3', 'LLM Engineer', 'Razorpay', 'instahyre', 'Bengaluru', 'Not disclosed', [4, 8], 1, true, 0.84, 0.82, ['LLM', 'Python', 'RAG', 'Go'], 'Work on LLM-powered support automation for merchants: prompt pipelines, guardrails and offline evals.'],
  ['j4', 'ML Engineer II', 'Swiggy', 'naukri', 'Bengaluru', '30–42 LPA', [3, 6], 2, false, 0.81, 0.79, ['Python', 'ML', 'Spark', 'Recommendations'], 'Improve ranking and recommendation models for food and Instamart discovery at high traffic.'],
  ['j5', 'AI Engineer', 'CRED', 'hirist', 'Bengaluru', '25–38 LPA', [5, 99], 1, true, 0.79, 0.78, ['LLM', 'Python', 'AWS', 'NLP'], 'Prototype and harden GenAI features across the member app, from intent detection to summarisation.'],
  ['j6', 'Applied Scientist, NLP', 'PhonePe', 'naukri', 'Bengaluru', '24–34 LPA', [3, 5], 3, true, 0.76, 0.75, ['NLP', 'PyTorch', 'Transformers', 'Python'], 'Train and serve NLP models for fraud signals and customer support in 11 Indian languages.'],
  ['j7', 'Deep Learning Engineer', 'Tredence', 'naukri', 'Gurugram', '18–28 LPA', [3, 6], 0, true, 0.74, 0.74, ['Deep Learning', 'CV', 'TensorFlow', 'PyTorch'], 'Deliver vision and forecasting models for CPG clients. Strong experiment tracking expected.'],
  ['j8', 'AI Cloud Engineer', 'TCS', 'hirist', 'Noida', '12–20 LPA', [-1, -1], 4, true, 0.71, 0.69, ['Azure', 'MLOps', 'Python', 'Docker'], 'Set up ML platforms on Azure for banking clients: pipelines, model registry and monitoring.'],
  ['j9', 'Python AI Engineer', 'Meesho', 'instahyre', 'Bengaluru', '26–36 LPA', [3, 7], 2, true, 0.69, 0.68, ['Python', 'FastAPI', 'LLM', 'SQL'], 'Build Python services that put LLM features in front of sellers: catalog writing, tagging and QA.'],
  ['j18', 'Research Engineer, Speech', 'Sarvam AI', 'naukri', 'Bengaluru', 'Not disclosed', [3, 6], 3, false, 0.62, 0.63, ['PyTorch', 'Deep Learning', 'Speech', 'Python'], 'Scale ASR and TTS training for Indian languages across multi-node GPU clusters.'],
  ['j10', 'ML Engineer', 'LatentView Analytics', 'naukri', 'Remote', '14–22 LPA', [2, 5], 5, true, 0.64, 0.62, ['Python', 'ML', 'scikit-learn', 'SQL'], 'Deliver ML solutions for analytics clients, from feature engineering to deployment.', true],
  ['j11', 'Computer Vision Engineer', 'Infosys', 'naukri', 'Pune', '10–16 LPA', [3, 6], 6, false, 0.58, 0.56, ['CV', 'OpenCV', 'PyTorch'], 'Build defect-detection models for manufacturing clients and deploy them to edge devices.'],
  ['j12', 'MLOps Engineer', 'PhonePe', 'hirist', 'Pune', 'Not disclosed', [4, 8], 3, true, 0.55, 0.55, ['MLOps', 'Kubernetes', 'Kubeflow', 'AWS'], 'Run the feature store and model-serving stack, and cut deployment time for data science teams.'],
  ['j13', 'Data Scientist, GenAI', 'Fractal Analytics', 'hirist', 'Gurugram', '20–30 LPA', [3, 7], 7, false, 0.49, 0.5, ['GenAI', 'Python', 'Statistics'], 'Lead GenAI proofs of concept for insurance clients and turn the winners into products.'],
  ['j14', 'AI Engineer, Search', 'Swiggy', 'instahyre', 'Hyderabad', '28–38 LPA', [4, 6], 4, true, 0.47, 0.47, ['Elasticsearch', 'Python', 'LLM'], 'Improve query understanding and semantic retrieval for restaurant and dish search.'],
  ['j15', 'ML Platform Engineer', 'Razorpay', 'naukri', 'Remote', '32–45 LPA', [5, 9], 7, true, 0.41, 0.43, ['Kubernetes', 'Go', 'MLOps'], 'Build the internal platform data scientists use to train, ship and monitor models.'],
  ['j16', 'Junior AI Engineer', 'Infosys', 'hirist', 'Noida', '6–9 LPA', [-1, -1], 14, true, 0.33, 0.32, ['Python', 'ML'], 'Support AI delivery teams with data preparation, model training and testing.'],
  ['j17', 'AI/ML Engineer', 'TCS', 'naukri', 'Hyderabad', '9–15 LPA', [2, 4], 5, true, 0.29, 0.28, ['Python', 'TensorFlow', 'SQL'], 'Build and maintain ML models for a telecom client inside an established delivery team.'],
];

export function makeJobs(): Job[] {
  return RAW.map(([id, title, company, platform, location, salary, exp, days, easy, match, rank, skills, desc, applied]) => ({
    platform,
    job_id: id,
    title,
    company,
    location,
    salary,
    apply_url: URL_BASE[platform] + id,
    description: desc,
    skills,
    exp_min: exp[0],
    exp_max: exp[1],
    posted_days_ago: days,
    match_score: match,
    rank_score: rank,
    easy_apply: easy,
    already_applied: !!applied,
  }));
}

export const COUNTS: Record<Platform, number> = { naukri: 42, instahyre: 29, hirist: 16 };

/** Failures simulated during apply. j12 succeeds on retry; j9 never does. */
export const FAILS: Record<string, { reason: string; permanent: boolean }> = {
  j9: { reason: 'Employer form asks a custom question (notice-period buyout). Apply manually on Instahyre.', permanent: true },
  j12: { reason: 'Session timed out while submitting. A retry usually works.', permanent: false },
};

function at(daysBack: number, hm: string): string {
  const [h, m] = hm.split(':').map(Number);
  const d = new Date();
  d.setDate(d.getDate() - daysBack);
  d.setHours(h, m, 0, 0);
  // Keep "today" entries in the past even early in the morning.
  if (d.getTime() > Date.now()) d.setTime(Date.now() - (60 - m) * 60000);
  return localIso(d);
}

export function localIso(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

type RawApp = [number, string, string, string, Platform, AppStatus, string | null];
const RAW_APPS: RawApp[] = [
  [0, '10:42', 'Senior Data Scientist, LLMs', 'Tredence', 'naukri', 'applied', null],
  [0, '10:41', 'ML Engineer', 'LatentView Analytics', 'naukri', 'applied', null],
  [0, '10:40', 'AI Engineer', 'Infosys', 'hirist', 'failed', 'Session expired during submit'],
  [0, '10:39', 'GenAI Developer', 'TCS', 'hirist', 'applied', null],
  [0, '09:58', 'LLM Engineer', 'Razorpay', 'instahyre', 'dry_run', null],
  [0, '09:58', 'Applied Scientist, NLP', 'PhonePe', 'naukri', 'dry_run', null],
  [0, '09:58', 'ML Engineer II', 'Swiggy', 'naukri', 'skipped', 'Not Easy Apply'],
  [1, '18:20', 'NLP Engineer', 'Sarvam AI', 'instahyre', 'applied', null],
  [1, '18:19', 'Python Developer, AI', 'Meesho', 'instahyre', 'applied', null],
  [1, '18:19', 'AI Cloud Engineer', 'Infosys', 'naukri', 'failed', 'Employer form asks a custom question'],
  [2, '16:05', 'ML Engineer', 'Fractal Analytics', 'naukri', 'applied', null],
  [3, '11:20', 'Deep Learning Engineer', 'Tredence', 'hirist', 'skipped', 'Already applied'],
  [4, '19:44', 'MLOps Engineer', 'CRED', 'instahyre', 'applied', null],
  [9, '10:02', 'AI Engineer', 'Swiggy', 'naukri', 'applied', null],
  [13, '15:37', 'Data Scientist', 'TCS', 'hirist', 'failed', 'Session expired during submit'],
  [18, '12:10', 'Computer Vision Engineer', 'Infosys', 'naukri', 'dry_run', null],
];

export function makeApps(): Application[] {
  return RAW_APPS.map(([days, hm, title, company, platform, status, error], i) => ({
    id: 100 - i,
    platform,
    job_id: `a${i}`,
    title,
    company,
    location: 'Bengaluru',
    apply_url: `${URL_BASE[platform]}a${i}`,
    status,
    error,
    applied_at: at(days, hm),
  }));
}

export function makeProfile(): Profile {
  return {
    name: 'Rohan Mehta',
    email: 'rohan.mehta@example.com',
    phone: '98765 43210',
    location: 'Gurugram, Haryana',
    experience_years: 4,
    excluded_companies: ['TCS'],
    resume: { filename: 'Rohan_Mehta_Resume_2026.pdf', size_bytes: 188_416, uploaded_at: at(26, '12:00') },
    autofill: {
      current_ctc: '18',
      expected_ctc: '28',
      total_experience: '4',
      notice_period: '30 days',
      gender: 'male',
      highest_qualification: 'B.Tech, Computer Science',
      graduation_year: '2021',
      primary_cloud: 'AWS',
      contract_based: 'No',
      offer_in_hand: 'No',
      last_working_day: 'Currently Working',
      experience: { python: '4', ml: '4', dl: '3', nlp: '3', genai: '2', llm: '2', langchain: '1.5', rag: '2', tensorflow: '2', pytorch: '3', 'scikit-learn': '4', mlops: '2', cv: '1' },
      preferred_locations: ['Delhi NCR', 'Gurugram', 'Noida', 'Bengaluru', 'Remote'],
    },
  };
}

// ---------- resume review ----------
type RawIssue = { id: string; sev: Severity; title: string; where: string; why: string; before: string; after: string; note?: string; gain: Partial<Record<'acc' | 'ats' | 'fit' | 'impact', number>> };
const ISSUES: RawIssue[] = [
  { id: 'i1', sev: 'mistake', title: 'Job dates overlap', where: 'Experience', why: 'Kite Labs starts Mar 2023 but Nimbus Analytics ends Aug 2023. Recruiters read an unexplained overlap as a red flag, and background checks will catch it.', before: 'Data Scientist · Nimbus Analytics · 03/2021 – Aug 2023', after: 'Data Scientist · Nimbus Analytics · Mar 2021 – Feb 2023', note: 'Use the dates on your relieving letter. If you did overlap (notice period, part-time), say so in one line.', gain: { acc: 10 } },
  { id: 'i2', sev: 'mistake', title: 'Phone number doesn’t match your profile', where: 'Header', why: 'Your resume says 98765 43201, your profile says 98765 43210. Autofill sends the profile number, so recruiters see two different numbers.', before: '+91 98765 43201', after: '+91 98765 43210', note: 'If the resume is right, fix it in Profile instead.', gain: { acc: 10 } },
  { id: 'i3', sev: 'mistake', title: 'Spelling: “Retreival”', where: 'Projects', why: 'A typo in the title of your most relevant project. ATS keyword search for “retrieval” will also miss it.', before: 'Retreival-augmented QA over Indian legal judgments', after: 'Retrieval-augmented QA over Indian legal judgments', gain: { acc: 6, ats: 2 } },
  { id: 'i5', sev: 'change', title: 'Summary is generic', where: 'Summary', why: 'It doesn’t say your role, years or stack, and it’s the first thing a screener reads.', before: 'Passionate AI/ML engineer looking for challenging opportunities in a growth-oriented organisation.', after: 'AI/ML engineer with 4 years building and shipping ML and LLM systems in Python: RAG assistants, LoRA fine-tuning and model deployment on AWS. Looking for {role} roles.', note: 'Built only from what’s already on your resume.', gain: { fit: 6, impact: 4 } },
  { id: 'i6', sev: 'change', title: 'Bullet describes a duty, not a result', where: 'Experience · Kite Labs', why: '“Worked on” says nothing about scale or outcome. This is your strongest GenAI line, so it should carry numbers.', before: 'Worked on RAG chatbot for internal documents.', after: 'Built a RAG assistant over [N] internal documents with LangChain and FAISS, used by [N] support agents; cut answer lookup time by [X%].', note: 'Fill the brackets with real numbers. Don’t estimate figures you can’t back up in an interview.', gain: { impact: 12 } },
  { id: 'i8', sev: 'change', title: '“Responsible for” hides what you did', where: 'Experience · Kite Labs', why: 'Lead with the action and what it achieved.', before: 'Responsible for model deployment using Docker and AWS.', after: 'Deployed [N] models to AWS SageMaker endpoints in Docker, serving [N] requests a day at p95 [X] ms.', note: 'Fill the brackets with real numbers.', gain: { impact: 10 } },
  { id: 'i7', sev: 'change', title: 'Skills list is long and inconsistent', where: 'Skills', why: '27 tools in one line, no grouping. “Pytorch”, “Tensorflow” and “Langchain” don’t match the official names, and MS Word and Excel dilute it.', before: 'Python, Pytorch, Tensorflow, Langchain, scikit-learn, XGBoost, Pandas, … MS Word, Excel', after: 'LLM and GenAI: LangChain, Hugging Face, FAISS, LoRA · ML: PyTorch, TensorFlow, scikit-learn, XGBoost · MLOps: Docker, AWS SageMaker, FastAPI, Git · Data: Python, SQL, Pandas', gain: { ats: 6, fit: 4 } },
  { id: 'i9', sev: 'change', title: 'Missing keywords your target jobs ask for', where: 'Whole resume', why: '', before: '', after: '', note: 'Add these only where you have real experience. The Prepare tab has a plan to close the gaps.', gain: { fit: 10 } },
  { id: 'i10', sev: 'change', title: 'Your strongest project is at the bottom', where: 'Projects', why: 'For {role} roles the legal-QA project is your best evidence, but it sits below older analytics work.', before: 'Order: Summary, Experience (Kite Labs, Nimbus), Projects, Skills', after: 'Order: Summary, Experience (Kite Labs), Projects, Experience (Nimbus), Skills', note: 'Job MCP can keep this as a separate resume variant for {role} applications.', gain: { fit: 5 } },
  { id: 'i11', sev: 'polish', title: 'Mixed date formats', where: 'Experience', why: '“03/2021” next to “Mar 2023” looks careless.', before: '03/2021', after: 'Mar 2021', gain: { ats: 3 } },
  { id: 'i12', sev: 'polish', title: 'Drop “References available on request”', where: 'Other', why: 'Recruiters assume it. The line costs space and adds nothing.', before: 'References available on request.', after: '(remove)', gain: { ats: 1 } },
  { id: 'i13', sev: 'polish', title: 'Two pages for 4 years of experience', where: 'Whole resume', why: 'At 4 years one page is expected. The skills cleanup and dropping the Power BI and Excel lines get you there.', before: '2 pages', after: '1 page', gain: { ats: 4 } },
];

type RawLine = { t: string; k?: 'name' | 'role'; ids?: string[] };
const RES: { title: string; lines: RawLine[] }[] = [
  { title: '', lines: [{ t: 'Rohan Mehta', k: 'name' }, { t: 'Gurugram · rohan.mehta@example.com · +91 98765 43201 · github.com/rohanm', ids: ['i2'] }] },
  { title: 'Summary', lines: [{ t: 'Passionate AI/ML engineer looking for challenging opportunities in a growth-oriented organisation.', ids: ['i5'] }] },
  {
    title: 'Experience',
    lines: [
      { t: 'ML Engineer · Kite Labs, Gurugram · Mar 2023 – Present', k: 'role' },
      { t: '• Worked on RAG chatbot for internal documents.', ids: ['i6'] },
      { t: '• Responsible for model deployment using Docker and AWS.', ids: ['i8'] },
      { t: '• Fine-tuned Llama 2 7B with LoRA for support-ticket classification; F1 0.71 → 0.84.' },
      { t: 'Data Scientist · Nimbus Analytics, Noida · 03/2021 – Aug 2023', k: 'role', ids: ['i1', 'i11'] },
      { t: '• Built churn models (XGBoost) for a telecom client.' },
      { t: '• Created dashboards in Power BI and Excel for weekly reviews.', ids: ['i13'] },
    ],
  },
  { title: 'Projects', lines: [{ t: 'Retreival-augmented QA over Indian legal judgments · LangChain, FAISS', k: 'role', ids: ['i3', 'i10'] }, { t: '• Evaluated on 200 hand-labelled questions; 78% answer accuracy.' }] },
  { title: 'Skills', lines: [{ t: 'Python, Pytorch, Tensorflow, Langchain, scikit-learn, XGBoost, Pandas, NumPy, SQL, Docker, AWS, SageMaker, FastAPI, Flask, Git, Linux, Hugging Face, FAISS, OpenCV, NLTK, spaCy, Matplotlib, Seaborn, Power BI, Tableau, MS Word, Excel', ids: ['i7'] }] },
  { title: 'Education', lines: [{ t: 'B.Tech, Computer Science · 2021' }] },
  { title: 'Other', lines: [{ t: 'References available on request.', ids: ['i12'] }] },
];

export const DEMAND: Record<string, { jobs: number; fit: number; rows: [string, number, DemandRow['you']][] }> = {
  'GenAI Engineer': { jobs: 23, fit: 61, rows: [['Python', 23, 'strong'], ['LLM APIs and prompting', 21, 'strong'], ['RAG', 19, 'strong'], ['LangChain / LlamaIndex', 16, 'some'], ['LLM evaluation', 14, 'gap'], ['Vector databases', 13, 'some'], ['AWS', 12, 'strong'], ['Fine-tuning (LoRA, PEFT)', 11, 'strong'], ['Kubernetes', 11, 'gap'], ['Agents and tool calling', 10, 'gap'], ['vLLM / model serving', 9, 'gap']] },
  'LLM Engineer': { jobs: 17, fit: 57, rows: [['Python', 17, 'strong'], ['Fine-tuning (LoRA, PEFT)', 14, 'strong'], ['LLM evaluation', 13, 'gap'], ['vLLM / model serving', 12, 'gap'], ['RAG', 11, 'strong'], ['PyTorch', 11, 'strong'], ['Distributed training', 8, 'gap'], ['Quantisation', 7, 'some'], ['Kubernetes', 6, 'gap']] },
  'ML Engineer': { jobs: 31, fit: 76, rows: [['Python', 31, 'strong'], ['scikit-learn / XGBoost', 24, 'strong'], ['SQL', 22, 'some'], ['MLOps (MLflow, CI/CD)', 19, 'some'], ['PyTorch', 17, 'strong'], ['Docker', 16, 'strong'], ['AWS', 15, 'strong'], ['Spark', 14, 'gap'], ['A/B testing', 12, 'gap'], ['Feature stores', 9, 'gap']] },
};

type RawPlan = [1 | 2, string, PlanItem['type'], string, number];
const PLAN: Record<'genai' | 'ml', RawPlan[]> = {
  genai: [[1, 'Fix the 3 resume mistakes on the Review tab', 'Resume', '30 min', 0.5], [1, 'Add an evaluation section to your legal-QA project: recall@5, faithfulness and answer relevance on your 200 labelled questions', 'Build', '6 h', 6], [1, 'Serve a 7B model with vLLM and compare throughput with plain Hugging Face generate', 'Build', '4 h', 4], [1, 'Practise 2 GenAI system design questions out loud', 'Practice', '2 h', 2], [2, 'Deploy your FastAPI model service on a local Kubernetes cluster (kind or minikube)', 'Learn', '5 h', 5], [2, 'Build a small tool-calling agent over your RAG index and log where it fails', 'Build', '4 h', 4], [2, 'Write STAR stories for your 3 strongest projects', 'Practice', '2 h', 2], [2, 'Run 2 mock interviews with {ai}: LLM and GenAI, then system design', 'Practice', '2 h', 2]],
  ml: [[1, 'Fix the 3 resume mistakes on the Review tab', 'Resume', '30 min', 0.5], [1, 'Rewrite the churn-model bullets with the business metric they moved', 'Resume', '1 h', 1], [1, 'Refresh Spark: rebuild one feature pipeline in PySpark', 'Learn', '5 h', 5], [1, 'Practise 2 ML system design questions out loud', 'Practice', '2 h', 2], [2, 'Design and analyse a mock A/B test end to end, including a power calculation', 'Learn', '4 h', 4], [2, 'Add MLflow tracking and a CI check to one existing project', 'Build', '4 h', 4], [2, 'Write STAR stories for your 3 strongest projects', 'Practice', '2 h', 2], [2, 'Run 2 mock interviews with {ai}: ML fundamentals, then ML system design', 'Practice', '2 h', 2]],
};

type RawQ = [string, Round, 'all' | 'genai' | 'ml', string, string, string[], string];
const QS: RawQ[] = [
  ['f1', 'fund', 'all', 'Explain the bias–variance trade-off using your churn model.', 'Checks that you can tie theory to your own work.', ['High bias: too simple, underfits non-linear churn signals', 'High variance: deep trees memorising one quarter of data', 'How you tuned it: depth, regularisation, time-based cross-validation', 'What you’d do differently now'], 'Churn models (XGBoost) at Nimbus Analytics'],
  ['f2', 'fund', 'all', 'Precision or recall: which mattered more for your ticket classifier, and why?', 'Probes whether you chose metrics from the business cost.', ['Cost of a false positive vs a false negative when routing tickets', 'How the decision threshold was set', 'Why you reported F1, and its limits', 'Per-class metrics for imbalanced labels'], 'Llama 2 LoRA ticket classifier, F1 0.71 → 0.84'],
  ['f3', 'fund', 'all', 'How does LoRA reduce the number of trainable parameters?', 'Common follow-up when a resume mentions fine-tuning.', ['Freeze base weights; learn a low-rank update A·B per layer', 'Rank r trades capacity for size', 'Which layers you targeted and why', 'Merging adapters for inference'], 'Llama 2 LoRA ticket classifier'],
  ['l1', 'llm', 'genai', 'How would you evaluate a RAG system before shipping it?', 'Evaluation is the most-asked gap in your matched listings.', ['Retrieval: recall@k and MRR on a labelled question set', 'Generation: faithfulness to retrieved context, answer relevance', 'LLM-as-judge, calibrated against human spot checks', 'A regression set that runs on every change'], 'Legal-QA project: 200 hand-labelled questions, 78% accuracy'],
  ['l2', 'llm', 'genai', 'When would you fine-tune instead of using RAG or better prompts?', 'Tests judgement, not just tools.', ['Fine-tune for behaviour, format or style; RAG for fresh or private knowledge', 'Data you need and its labelling cost', 'Inference latency and cost', 'Often both: a tuned model reading retrieved context'], 'You’ve done both: the Kite Labs RAG assistant and the LoRA classifier'],
  ['l3', 'llm', 'genai', 'How do you reduce hallucinations in a customer-facing assistant?', 'Shows you think about users, not just models.', ['Fix retrieval first: chunking, hybrid search, reranking', 'Answer only from context, with citations', 'Allow and test “I don’t know”', 'Measure it with a faithfulness score on a fixed set'], ''],
  ['m1', 'llm', 'ml', 'How do you detect and handle data drift after deployment?', 'Production ML is most of an ML Engineer’s job.', ['Monitor input distributions (PSI, KS) and prediction distributions', 'Track delayed ground truth when it arrives', 'Alert thresholds and a retraining trigger', 'Shadow-test the retrained model before switching'], 'Churn models at Nimbus Analytics'],
  ['m2', 'llm', 'ml', 'Walk through an A/B test for a new ranking model.', 'A/B testing is a gap in your matched listings.', ['Primary metric and guardrail metrics', 'Randomisation unit and sample size', 'Run length and novelty effects', 'Statistical vs practical significance'], ''],
  ['m3', 'llm', 'ml', 'What goes into a feature store, and when is it worth it?', 'Feature stores appear in 9 of your matched listings.', ['Shared, versioned features for training and serving', 'Point-in-time correctness to avoid leakage', 'Online vs offline stores', 'Worth it once several models reuse features'], ''],
  ['d1', 'design', 'genai', 'Design a Q&A assistant over 10 million internal documents with per-team access control.', 'Classic GenAI design round; maps to your RAG work.', ['Ingestion: parsing, chunking, metadata including ACLs', 'Embeddings plus hybrid search, filtered by ACL at query time', 'Reranker, then generation with citations', 'Caching, evaluation set, feedback loop and monitoring'], 'Kite Labs RAG assistant over internal documents'],
  ['d2', 'design', 'genai', 'Serve a 7B model at 50 requests a second with p95 under 2 seconds.', 'Model serving is a gap; expect it in LLM-heavy teams.', ['vLLM with continuous batching and paged attention', 'Quantisation (AWQ, GPTQ) vs quality loss', 'Size GPUs from tokens per second, plus headroom', 'Streaming, autoscaling and load tests'], ''],
  ['d3', 'design', 'ml', 'Design a churn-prediction system that scores 5 million users daily.', 'Lets you lead with work you’ve already done.', ['Batch features from the warehouse; a daily scoring job', 'Model choice and calibration', 'Pushing scores to the CRM, with monitoring', 'Retraining cadence and drift checks'], 'Churn models at Nimbus Analytics'],
  ['d4', 'design', 'ml', 'Design real-time fraud scoring for UPI payments under 100 ms.', 'Tests latency budgets and online features.', ['Streaming features from an online store', 'A lightweight model plus rules', 'Latency budget per stage', 'Labels from chargebacks, with delay'], ''],
  ['c1', 'code', 'all', 'Split text into token-bounded chunks with overlap.', 'A frequent warm-up in GenAI coding rounds.', ['Tokenise once; slide a window of size n with stride n − overlap', 'Handle the last partial window', 'Map token spans back to text', 'Edge cases: empty text, overlap ≥ size'], ''],
  ['c2', 'code', 'all', 'Implement a token-bucket rate limiter for an LLM API client.', 'Checks practical Python, state and concurrency.', ['Capacity and refill rate', 'Refill lazily from elapsed time', 'Thread safety with a lock', 'An asyncio version'], ''],
  ['c3', 'code', 'all', 'Return the k most frequent words from a large log stream.', 'Classic data-structures question.', ['Counter if it fits in memory', 'Heap of size k: O(n log k)', 'Count-min sketch if it doesn’t fit', 'Normalise case and punctuation first'], ''],
  ['b1', 'behav', 'all', 'Tell me about a model that didn’t work in production.', 'Interviewers look for ownership and what you learnt.', ['Situation and what you expected', 'What broke and how you noticed', 'What you changed', 'What you do differently now'], ''],
  ['b2', 'behav', 'all', 'Why are you looking to move from Kite Labs?', 'Asked in almost every first round.', ['What you want to do more of', 'Tie it to this role', 'Stay positive about your current team'], ''],
  ['b3', 'behav', 'all', 'Describe a time you disagreed with a stakeholder about what to build.', 'Tests communication and judgement.', ['The disagreement in one line', 'The data you brought', 'The outcome and what you learnt'], ''],
];

const KEYMAP: Record<'acc' | 'ats' | 'fit' | 'impact', ScoreKey> = { acc: 'accuracy', ats: 'ats', fit: 'fit', impact: 'impact' };

function joinList(a: string[]): string {
  return a.length <= 1 ? a.join('') : `${a.slice(0, -1).join(', ')} and ${a[a.length - 1]}`;
}

export function makeIssues(role: string): Issue[] {
  const rd = DEMAND[role] ?? DEMAND['GenAI Engineer'];
  const sub = (t: string) => t.split('{role}').join(role);
  const lineIds = new Map<string, string[]>();
  RES.forEach((sec, si) => sec.lines.forEach((l, li) => (l.ids ?? []).forEach((id) => lineIds.set(id, [...(lineIds.get(id) ?? []), `s${si}l${li}`]))));
  const gaps = rd.rows.filter((r) => r[2] === 'gap').sort((a, b) => b[1] - a[1]).slice(0, 3);
  return ISSUES.map((it) => {
    const gain: Issue['gain'] = {};
    (Object.keys(it.gain) as (keyof RawIssue['gain'])[]).forEach((k) => (gain[KEYMAP[k]] = it.gain[k]));
    const issue: Issue = { id: it.id, severity: it.sev, title: it.title, where: it.where, why: sub(it.why), before: sub(it.before), after: sub(it.after), note: it.note ? sub(it.note) : '', gain, line_ids: lineIds.get(it.id) ?? [], status: 'open' };
    if (it.id === 'i9') {
      issue.why = `${joinList(gaps.map((g) => g[0]))} appear in ${joinList(gaps.map((g) => String(g[1])))} of your ${rd.jobs} matched ${role} jobs, and aren’t on your resume.`;
      issue.before = `No mention of ${joinList(gaps.map((g) => g[0]))}`;
      issue.after = 'A line in Skills plus one project bullet for each, once you have hands-on work to point to';
    }
    return issue;
  });
}

export function makeSections(): ResumeSection[] {
  return RES.map((sec, si) => ({
    title: sec.title,
    lines: sec.lines.map((l, li) => ({ id: `s${si}l${li}`, text: l.t, kind: l.k ?? (l.t.startsWith('•') ? 'bullet' : 'text') })),
  }));
}

export function makePlan(role: string, ai: string): PlanItem[] {
  const rk = role === 'ML Engineer' ? 'ml' : 'genai';
  return PLAN[rk].map(([week, text, type, time, hours], i) => ({ id: `${rk}-p${i}`, week, text: text.replace('{ai}', ai), type, time, hours, done: false }));
}

export function makeQuestions(role: string): Question[] {
  const rk = role === 'ML Engineer' ? 'ml' : 'genai';
  return QS.filter((q) => q[2] === 'all' || q[2] === rk).map(([id, round, , q, why, outline, from_resume]) => ({ id, round, q, why, outline, from_resume, practised: false }));
}

export function baseScores(role: string): Record<ScoreKey, number> {
  return { accuracy: 74, impact: 48, fit: (DEMAND[role] ?? DEMAND['GenAI Engineer']).fit, ats: 82 };
}
