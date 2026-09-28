CREATE DATABASE IF NOT EXISTS skill_decay_tracker;

USE skill_decay_tracker;


-- =========================================================
-- USERS
-- =========================================================

CREATE TABLE IF NOT EXISTS users (

    id INT AUTO_INCREMENT PRIMARY KEY,

    name VARCHAR(100) NOT NULL,

    email VARCHAR(150) NOT NULL UNIQUE,

    password VARCHAR(255) NULL,

    google_id VARCHAR(255) NULL,

    auth_provider VARCHAR(50) DEFAULT 'local',

    avatar_url VARCHAR(500) NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);


-- =========================================================
-- SKILLS
-- =========================================================

CREATE TABLE IF NOT EXISTS skills (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    skill_name VARCHAR(100) NOT NULL,

    category VARCHAR(100) NOT NULL,

    initial_level ENUM(
        'Beginner',
        'Intermediate',
        'Advanced'
    ) NOT NULL DEFAULT 'Beginner',

    target_frequency INT NOT NULL DEFAULT 7,

    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_skills_user

        FOREIGN KEY (user_id)
        REFERENCES users(id)

        ON DELETE CASCADE

);


-- =========================================================
-- PRACTICE SESSIONS
-- =========================================================

CREATE TABLE IF NOT EXISTS practice_sessions (

    id INT AUTO_INCREMENT PRIMARY KEY,

    skill_id INT NOT NULL,

    practice_date DATE NOT NULL,

    duration INT NOT NULL,

    difficulty ENUM(
        'Easy',
        'Medium',
        'Hard'
    ) NOT NULL DEFAULT 'Medium',

    performance INT NOT NULL,

    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_practice_skill

        FOREIGN KEY (skill_id)
        REFERENCES skills(id)

        ON DELETE CASCADE

);


-- =========================================================
-- SKILL HISTORY
-- =========================================================

CREATE TABLE IF NOT EXISTS skill_history (

    id INT AUTO_INCREMENT PRIMARY KEY,

    skill_id INT NOT NULL,

    health_score DECIMAL(5,2) NOT NULL,

    status VARCHAR(50) NOT NULL,

    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_history_skill

        FOREIGN KEY (skill_id)
        REFERENCES skills(id)

        ON DELETE CASCADE

);