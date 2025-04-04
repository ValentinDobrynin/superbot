# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2024-04-04

### Fixed
- Fixed error in `/summ` command by replacing `_make_request` with `chat_completion`
- Removed exposed database credentials from configuration
- Updated security documentation with correct contact information

### Changed
- Updated installation instructions with detailed PostgreSQL setup
- Improved documentation clarity and organization

## [1.0.0] - 2024-04-04

### Added
- Initial release
- Basic bot functionality with OpenAI integration
- Multiple chat styles (work, friendly, mixed)
- Smart mode for adaptive responses
- Response probability control
- Importance threshold for message filtering
- Silent mode for learning without responding
- Message tagging and threading
- Chat analytics and statistics

### Changed
- Changed default chat mode to silent mode when bot is added to a new chat
- Updated documentation with current features and setup instructions
- Improved error handling and logging

### Fixed
- Removed unused is_active functionality
- Fixed documentation links
- Updated security guidelines

### Security
- Added security policy and guidelines
- Implemented proper input validation
- Added rate limiting
- Improved error handling to prevent information leakage

## [0.1.0] - 2024-03-01

### Added
- Initial development version
- Basic bot structure
- Database models and migrations
- Command handlers
- Message handlers
- OpenAI service integration
- Context service for message history
- Notification service for important events

### Changed
- None

### Fixed
- None

### Security
- Basic security measures implemented
- Environment variables for sensitive data
- Input validation
- SQL injection prevention 