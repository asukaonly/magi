"""
L5: Capability Memory Layer

Extract reusable capabilities from successful experiences
Supports capability storage, querying, and reuse
"""
import logging
import time
from typing import Dict, Any, List, Optional, Callable, Set
from datetime import datetime
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


class Capability:
    """
    Capability definition

    Reusable capability extracted from successful experiences
    """

    def __init__(
        self,
        capability_id: str,
        name: str,
        description: str,
        trigger_pattern: Dict[str, Any],  # Trigger conditions
        action: Dict[str, Any],           # Execution action
        success_rate: float = 0.0,        # Success rate
        usage_count: int = 0,             # Usage count
        avg_duration: float = 0.0,         # Average execution time
        last_used: float = 0,             # Last used time
        created_at: float = None,          # Creation time
        examples: List[Dict[str, Any]] = None,  # Success cases
        failures: List[str] = None,        # Failure lessons
    ):
        self.capability_id = capability_id
        self.name = name
        self.description = description
        self.trigger_pattern = trigger_pattern
        self.action = action
        self.success_rate = success_rate
        self.usage_count = usage_count
        self.avg_duration = avg_duration
        self.last_used = last_used
        self.created_at = created_at or time.time()
        self.examples = examples or []
        self.failures = failures or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "trigger_pattern": self.trigger_pattern,
            "action": self.action,
            "success_rate": self.success_rate,
            "usage_count": self.usage_count,
            "avg_duration": self.avg_duration,
            "last_used": self.last_used,
            "created_at": self.created_at,
            "examples": self.examples,
            "failures": self.failures,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Capability":
        return cls(**data)

    def matches(self, context: Dict[str, Any]) -> float:
        """
        Determine if capability matches current context

        Args:
            context: Context information

        Returns:
            Match score (0-1)
        """
        score = 0.0

        # Check trigger conditions
        pattern = self.trigger_pattern

        # Check type match
        if "event_types" in pattern:
            context_type = context.get("event_type", "")
            if context_type in pattern["event_types"]:
                score += 0.3

        # Check keyword match
        if "keywords" in pattern:
            context_text = str(context.get("message", ""))
            for keyword in pattern["keywords"]:
                if keyword.lower() in context_text.lower():
                    score += 0.2

        # Check parameter match
        if "requires_params" in pattern:
            context_params = context.get("parameters", {})
            required = pattern["requires_params"]
            if all(k in context_params for k in required):
                score += 0.5

        return min(score, 1.0)


class CapabilityMemory:
    """
    Capability memory system

    Manages capability extraction, storage, querying and reuse
    """

    def __init__(self, persist_path: str = None):
        """
        initialize capability memory

        Args:
            persist_path: persistence file path
        """
        self.persist_path = persist_path

        # Capability store: {capability_id: Capability}
        self._capabilities: Dict[str, Capability] = {}

        # Usage statistics: {capability_id: {attempt: total, success: success_count}}
        self._stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"attempt": 0, "success": 0})

        # Blacklist: capabilities with low success rate
        self._blacklist: Set[str] = set()

        # Load persisted data
        if persist_path:
            self._load_from_disk()

    def record_attempt(
        self,
        task_id: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        success: bool,
        duration: float = 0.0,
        error: str = None,
    ):
        """
        Record task execution attempt

        Args:
            task_id: Task id
            context: Context information
            action: Executed action
            success: Whether successful
            duration: Execution time
            error: error message
        """
        # Update statistics
        self._stats[task_id]["attempt"] += 1
        if success:
            self._stats[task_id]["success"] += 1

        # Calculate success rate
        stats = self._stats[task_id]
        success_rate = stats["success"] / stats["attempt"] if stats["attempt"] > 0 else 0

        # Check if capability extraction is needed
        if stats["attempt"] >= 3 and success_rate >= 0.7:
            self._extract_capability(task_id, context, action, stats)

        # Update statistics for existing capabilities
        for capability in self._capabilities.values():
            if capability.matches(context):
                capability.usage_count += 1
                capability.last_used = time.time()

                # Update success rate (exponential moving average)
                alpha = 0.3
                capability.success_rate = alpha * success_rate + (1 - alpha) * capability.success_rate

                # Update average execution time
                if duration > 0:
                    if capability.avg_duration > 0:
                        capability.avg_duration = 0.7 * capability.avg_duration + 0.3 * duration
                    else:
                        capability.avg_duration = duration

                # Record usage case or failure
                if success:
                    if len(capability.examples) < 10:
                        capability.examples.append({
                            "timestamp": time.time(),
                            "context": context,
                        })
                else:
                    if error and len(capability.failures) < 5:
                        capability.failures.append(error)

        # Check blacklist
        if success_rate < 0.3 and stats["attempt"] >= 5:
            self._blacklist.add(task_id)

        # persist
        if self.persist_path:
            self._save_to_disk()

    def _extract_capability(
        self,
        task_id: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        stats: Dict[str, int],
    ):
        """
        Extract capability from task execution

        Args:
            task_id: Task id
            context: Context
            action: Executed action
            stats: Statistics
        """
        # Generate trigger pattern
        trigger_pattern = self._analyze_trigger_pattern(context, action)

        capability_id = f"cap_{task_id}"

        capability = Capability(
            capability_id=capability_id,
            name=self._generate_capability_name(context, action),
            description=f"Capability extracted from task '{task_id}'",
            trigger_pattern=trigger_pattern,
            action=action,
            success_rate=stats["success"] / stats["attempt"],
            usage_count=stats["attempt"],
            avg_duration=0.0,
            last_used=time.time(),
        )

        self._capabilities[capability_id] = capability
        logger.info(f"Capability extracted: {capability_id}")

    def _analyze_trigger_pattern(self, context: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze trigger conditions"""
        pattern = {
            "event_types": [],
            "keywords": [],
            "requires_params": [],
        }

        # Extract type from context
        if "event_type" in context:
            pattern["event_types"].append(context["event_type"])

        # Extract parameters from action
        if "tool" in action:
            pattern["keywords"].append(action["tool"])

        # Extract keywords from message
        message = context.get("message", "")
        if isinstance(message, str):
            # Simple keyword extraction
            words = message.split()
            pattern["keywords"].extend([w for w in words if len(w) > 3])

        return pattern

    def _generate_capability_name(self, context: Dict[str, Any], action: Dict[str, Any]) -> str:
        """Generate capability name"""
        tool = action.get("tool", "")
        event_type = context.get("event_type", "")

        if tool:
            return f"{tool} capability"
        elif event_type:
            return f"{event_type} handling capability"
        else:
            return "general capability"

    def find_capability(
        self,
        context: Dict[str, Any],
        threshold: float = 0.5,
    ) -> Optional[Capability]:
        """
        Find matching capability

        Args:
            context: Context information
            threshold: Match threshold

        Returns:
            Matching capability, or None
        """
        best_capability = None
        best_score = threshold

        for capability in self._capabilities.values():
            # Skip blacklist
            if capability.capability_id in self._blacklist:
                continue

            score = capability.matches(context)
            if score > best_score:
                best_score = score
                best_capability = capability

        return best_capability

    def get_all_capabilities(self) -> List[Capability]:
        """Get all capabilities"""
        return list(self._capabilities.values())

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        """Get specified capability"""
        return self._capabilities.get(capability_id)

    def delete_capability(self, capability_id: str) -> bool:
        """
        Delete capability

        Args:
            capability_id: Capability id

        Returns:
            Whether deletion was successful
        """
        if capability_id in self._capabilities:
            del self._capabilities[capability_id]
            if capability_id in self._stats:
                del self._stats[capability_id]
            self._blacklist.discard(capability_id)

            if self.persist_path:
                self._save_to_disk()

            logger.info(f"Capability deleted: {capability_id}")
            return True
        return False

    def _save_to_disk(self):
        """persist to disk"""
        if not self.persist_path:
            return

        try:
            data = {
                "capabilities": {
                    cap_id: cap.to_dict()
                    for cap_id, cap in self._capabilities.items()
                },
                "stats": dict(self._stats),
                "blacklist": list(self._blacklist),
            }

            with open(self.persist_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Capabilities saved to {self.persist_path}")
        except Exception as e:
            logger.error(f"Failed to save capabilities: {e}")

    def _load_from_disk(self):
        """Load from disk"""
        if not self.persist_path:
            return

        try:
            from pathlib import Path
            path = Path(self.persist_path)
            if not Path.exists():
                return

            with open(self.persist_path, "r") as f:
                data = json.load(f)

            # Load capabilities
            for cap_id, cap_data in data.get("capabilities", {}).items():
                self._capabilities[cap_id] = Capability.from_dict(cap_data)

            # Load statistics
            self._stats = defaultdict(lambda: {"attempt": 0, "success": 0})
            for task_id, stats in data.get("stats", {}).items():
                self._stats[task_id] = stats

            # Load blacklist
            self._blacklist = set(data.get("blacklist", []))

            logger.info(f"Capabilities loaded from {self.persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load capabilities: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics"""
        return {
            "total_capabilities": len(self._capabilities),
            "blacklist_count": len(self._blacklist),
            "most_used_capabilities": sorted(
                [(cap_id, cap.usage_count) for cap_id, cap in self._capabilities.items()],
                key=lambda x: x[1],
                reverse=True
            )[:5],
        }
