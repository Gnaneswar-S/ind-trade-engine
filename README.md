![Python](https://img.shields.io/badge/Python-3.13-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-App-red)
![Supabase](https://img.shields.io/badge/Supabase-Backend-green)
![Gemini](https://img.shields.io/badge/Google-Gemini-orange)
📦 Indian Trade Intelligence Engine

AI-powered Indian Trade Intelligence Engine for:

HS Code Classification (8-digit ITC HS)

Import Policy Analysis

Export Policy Analysis

GST & ITC Intelligence

User Authentication & Role Management

Usage Tracking & Admin Dashboard

Built using Streamlit + Supabase + Google Gemini API

🚀 Features
🔐 Authentication System

Email & Password Registration

Secure Login / Logout

Role-based access (User / Admin)

Auth logs tracking

📊 Trade Intelligence Modes

Import Mode

HS Code detection

Basic Customs Duty

IGST %

Import policy status

License requirement check

Export Mode

Export policy status

RoDTEP / RoSCTL applicability

Incentive notes

Knowledge Mode

GST rate

ITC availability

Compliance requirements

Risk flags

📈 Admin Dashboard

View all users

View authentication logs

View trade usage logs

Query analytics

🏗 Tech Stack

Frontend/UI → Streamlit

Backend/Auth/Database → Supabase

AI Engine → Google Gemini API

Language → Python 3.13

📂 Project Structure
ind_trade_engine/
│
├── app.py
├── supabase_service.py
├── gemini_service.py
├── gemini_test.py
├── requirements.txt
├── .env (NOT committed)
└── README.md
⚙️ Environment Variables

Create a .env file inside the project folder:

SUPABASE_URL=your_project_url
SUPABASE_SERVICE_KEY=your_service_role_key
GEMINI_API_KEY=your_gemini_api_key

⚠️ Do NOT commit .env to GitHub

🛠 Installation
1️⃣ Clone Repository
git clone https://github.com/yourusername/ind-trade-intelligence-engine.git
cd ind-trade-intelligence-engine
2️⃣ Create Virtual Environment
python -m venv venv
venv\Scripts\activate   # Windows
3️⃣ Install Dependencies
pip install -r requirements.txt
4️⃣ Run Application
streamlit run app.py
🗄 Required Supabase Tables

You must create the following tables:

profiles

user_id (uuid)

email (text)

role (text)

created_at (timestamp)

auth_logs

user_id (uuid)

email (text)

action (text)

timestamp (timestamptz)

trade_usage_logs

user_id (uuid)

email (text)

mode (text)

product (text)

hs_code (text, optional)

timestamp (timestamptz)

🔐 Security Notes

Service Role Key must NEVER be exposed to frontend

.env file must be ignored using .gitignore

Rotate keys if accidentally exposed

📊 Future Roadmap

Payment Integration

Subscription-based query limits

Advanced analytics dashboard

PDF export reports

Real-time customs data integration

👨‍💻 Author

Gnaneswar Somisetti
AI & Trade Intelligence Builder
