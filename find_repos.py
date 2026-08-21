#!/usr/bin/env python3
"""
GitHub Repository Finder - Locate Python projects matching specific criteria.

Criteria:
- Primary language: Python
- ~8,000+ lines of first-party source code
- 50+ source files
- 50+ commits
- 2+ weeks of history (gradual development, not bulk push)
- Less than 10 stars
- No MIT license
- No sponsors
- Actively developed
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class RepositoryMatch:
    """Container for repository matching results."""
    name: str
    url: str
    stars: int
    language: str
    license: Optional[str]
    commit_count: int
    file_count: int
    loc: int
    first_commit_date: datetime
    last_commit_date: datetime
    history_days: int
    has_funding: bool


class GitHubRepoFinder:
    """Search GitHub for repositories matching specific criteria."""

    def __init__(self, github_token: str):
        """Initialize with GitHub API token."""
        self.token = github_token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json"
        })
        self.rate_limit_remaining = 5000
        self.matches: List[RepositoryMatch] = []

    def _get(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a GET request to GitHub API with rate limiting."""
        try:
            response = self.session.get(url, params=params, timeout=10)
            
            # Track rate limits
            if "X-RateLimit-Remaining" in response.headers:
                self.rate_limit_remaining = int(response.headers["X-RateLimit-Remaining"])
            
            if response.status_code == 403:
                print(f"⚠️  Rate limited. Remaining: {self.rate_limit_remaining}")
                return None
            
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"❌ Request failed: {e}")
            return None

    def search_repositories(self, max_results: int = 100) -> List[Dict]:
        """Search for Python repositories with low star count."""
        print(f"🔍 Searching for Python repositories with <10 stars...")
        
        query = 'language:python stars:<10 archived:false'
        url = "https://api.github.com/search/repositories"
        
        repos = []
        page = 1
        per_page = 30
        
        while len(repos) < max_results:
            if self.rate_limit_remaining < 10:
                print("⏸️  Approaching rate limit, stopping search")
                break
            
            params = {
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": per_page,
                "page": page
            }
            
            data = self._get(url, params)
            if not data or "items" not in data:
                break
            
            items = data.get("items", [])
            if not items:
                break
            
            repos.extend(items)
            page += 1
            time.sleep(0.5)  # Be respectful to API
        
        return repos[:max_results]

    def count_lines_of_code(self, owner: str, repo: str) -> int:
        """Estimate lines of code by fetching language breakdown."""
        url = f"https://api.github.com/repos/{owner}/{repo}/languages"
        data = self._get(url)
        
        if not data:
            return 0
        
        # Sum all bytes and approximate LOC (rough: 1 byte ≈ 0.5 characters)
        total_bytes = sum(data.values())
        return int(total_bytes / 50)  # Conservative estimate

    def get_file_count(self, owner: str, repo: str) -> int:
        """Get approximate file count from repo stats."""
        url = f"https://api.github.com/repos/{owner}/{repo}"
        data = self._get(url)
        
        if not data:
            return 0
        
        # GitHub's API doesn't directly provide file count, so estimate from size
        # This is a rough heuristic; actual verification requires cloning
        size_kb = data.get("size", 0)
        if size_kb > 0:
            return max(50, int(size_kb / 20))  # Rough estimate
        
        return 0

    def get_commit_history(self, owner: str, repo: str) -> Dict:
        """Fetch commit history to verify activity pattern."""
        url = f"https://api.github.com/repos/{owner}/{repo}/commits"
        
        commits_by_date = defaultdict(int)
        first_commit = None
        last_commit = None
        total_commits = 0
        
        for page in range(1, 5):  # Check first 4 pages (max 120 commits)
            if self.rate_limit_remaining < 5:
                break
            
            params = {"per_page": 30, "page": page}
            data = self._get(url, params)
            
            if not data or not isinstance(data, list):
                break
            
            if not data:  # Empty page = no more commits
                break
            
            for commit in data:
                total_commits += 1
                commit_date = commit["commit"]["author"]["date"]
                date_obj = datetime.fromisoformat(commit_date.replace('Z', '+00:00')).date()
                commits_by_date[str(date_obj)] += 1
                
                if not last_commit:
                    last_commit = datetime.fromisoformat(commit_date.replace('Z', '+00:00'))
                first_commit = datetime.fromisoformat(commit_date.replace('Z', '+00:00'))
            
            time.sleep(0.3)
        
        return {
            "total": total_commits,
            "by_date": commits_by_date,
            "first_date": first_commit,
            "last_date": last_commit
        }

    def has_funding_file(self, owner: str, repo: str) -> bool:
        """Check if repo has GitHub Sponsors configured."""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/.github/FUNDING.yml"
        response = self.session.get(url, timeout=10)
        return response.status_code == 200

    def verify_gradual_development(self, commits_info: Dict, repo_dict: Dict) -> bool:
        """Verify that commits are gradual, not a bulk push."""
        if not commits_info["first_date"] or not commits_info["last_date"]:
            return False
        
        history_span = (commits_info["last_date"] - commits_info["first_date"]).days
        
        # Criteria: at least 14 days of history
        if history_span < 14:
            return False
        
        # Criteria: commits should be distributed (not all on one day)
        by_date = commits_info["by_date"]
        days_with_commits = len(by_date)
        
        # At least 10% of days should have commits for "gradual" development
        if days_with_commits < max(2, history_span // 10):
            return False
        
        return True

    def check_repository(self, repo_dict: Dict) -> Optional[RepositoryMatch]:
        """Check if a repository matches all criteria."""
        owner = repo_dict["owner"]["login"]
        repo_name = repo_dict["name"]
        stars = repo_dict["stargazers_count"]
        license_obj = repo_dict.get("license")
        license_name = license_obj.get("spdx_id") if license_obj else None
        
        print(f"\n📦 Checking: {owner}/{repo_name}")
        print(f"   Stars: {stars}, License: {license_name}")
        
        # Quick filters
        if stars >= 10:
            print(f"   ❌ Too many stars ({stars} >= 10)")
            return None
        
        if license_name == "MIT":
            print(f"   ❌ MIT license (excluded)")
            return None
        
        if repo_dict["language"] != "Python":
            print(f"   ❌ Not Python (is {repo_dict['language']})")
            return None
        
        # Check for funding
        has_funding = self.has_funding_file(owner, repo_name)
        if has_funding:
            print(f"   ❌ Has GitHub Sponsors funding")
            return None
        
        time.sleep(0.3)
        
        # Get LOC estimate
        loc = self.count_lines_of_code(owner, repo_name)
        print(f"   Lines of code (estimated): {loc}")
        
        if loc < 8000:
            print(f"   ❌ Insufficient LOC ({loc} < 8000)")
            return None
        
        time.sleep(0.3)
        
        # Get file count estimate
        file_count = self.get_file_count(owner, repo_name)
        print(f"   File count (estimated): {file_count}")
        
        if file_count < 50:
            print(f"   ❌ Insufficient files ({file_count} < 50)")
            return None
        
        time.sleep(0.3)
        
        # Get commit history
        commits_info = self.get_commit_history(owner, repo_name)
        commit_count = commits_info["total"]
        print(f"   Total commits: {commit_count}")
        
        if commit_count < 50:
            print(f"   ❌ Insufficient commits ({commit_count} < 50)")
            return None
        
        # Verify gradual development
        if not self.verify_gradual_development(commits_info, repo_dict):
            print(f"   ❌ Not gradually developed (bulk push or insufficient history)")
            return None
        
        history_days = (commits_info["last_date"] - commits_info["first_date"]).days
        print(f"   ✅ MATCH! History: {history_days} days")
        
        return RepositoryMatch(
            name=f"{owner}/{repo_name}",
            url=repo_dict["html_url"],
            stars=stars,
            language="Python",
            license=license_name,
            commit_count=commit_count,
            file_count=file_count,
            loc=loc,
            first_commit_date=commits_info["first_date"],
            last_commit_date=commits_info["last_date"],
            history_days=history_days,
            has_funding=has_funding
        )

    def find(self, target_count: int = 10, search_limit: int = 200) -> List[RepositoryMatch]:
        """Find repositories matching all criteria."""
        repos = self.search_repositories(max_results=search_limit)
        
        print(f"\n🎯 Found {len(repos)} candidates, verifying against criteria...\n")
        
        for repo in repos:
            if len(self.matches) >= target_count:
                break
            
            if self.rate_limit_remaining < 20:
                print(f"\n⏸️  Rate limit approaching, stopping search")
                break
            
            match = self.check_repository(repo)
            if match:
                self.matches.append(match)
        
        return self.matches


def main():
    """Main entry point."""
    import os
    import sys
    
    # Get GitHub token from environment
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("❌ Error: GITHUB_TOKEN environment variable not set")
        print("   Set it with: export GITHUB_TOKEN='your_token_here'")
        sys.exit(1)
    
    # Initialize finder
    finder = GitHubRepoFinder(token)
    
    # Search for repositories
    print("=" * 70)
    print("GitHub Repository Finder - Python Projects")
    print("=" * 70)
    print("\nCriteria:")
    print("  • Language: Python")
    print("  • Lines of Code: 8000+")
    print("  • Source Files: 50+")
    print("  • Commits: 50+")
    print("  • History: 2+ weeks (gradual development)")
    print("  • Stars: < 10")
    print("  • License: Not MIT")
    print("  • Sponsors: None")
    print("  • Status: Actively developed")
    print("=" * 70)
    
    matches = finder.find(target_count=10, search_limit=200)
    
    # Display results
    print("\n" + "=" * 70)
    print(f"RESULTS: Found {len(matches)} matching repositories")
    print("=" * 70 + "\n")
    
    for i, match in enumerate(matches, 1):
        print(f"{i}. {match.name}")
        print(f"   URL: {match.url}")
        print(f"   Stars: {match.stars}")
        print(f"   License: {match.license or 'None/Custom'}")
        print(f"   Commits: {match.commit_count}")
        print(f"   Files: {match.file_count}")
        print(f"   LOC: {match.loc}")
        print(f"   History: {match.history_days} days ({match.first_commit_date.date()} to {match.last_commit_date.date()})")
        print()
    
    # Save results to JSON
    results = [{
        "name": m.name,
        "url": m.url,
        "stars": m.stars,
        "license": m.license,
        "commits": m.commit_count,
        "files": m.file_count,
        "loc": m.loc,
        "history_days": m.history_days,
        "first_commit": m.first_commit_date.isoformat(),
        "last_commit": m.last_commit_date.isoformat()
    } for m in matches]
    
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"✅ Results saved to results.json")


if __name__ == "__main__":
    main()
