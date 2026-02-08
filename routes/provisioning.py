from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Optional
from pathlib import Path
import subprocess
import os
import logging
import time
import json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/provisioning", tags=["provisioning"])


class ProvisionRequest(BaseModel):
    """Request model for client provisioning"""
    public_key: str = Field(..., description="WireGuard public key of the client")
    machine_id: str = Field(..., description="Unique machine identifier")
    client_name: Optional[str] = Field(None, description="Optional client name/identifier")


class ProvisionResponse(BaseModel):
    """Response model for client provisioning"""
    success: bool
    message: str
    client_name: str
    client_ip: str
    assigned_ip: str
    wireguard_applied: Optional[bool] = Field(None, description="Whether WireGuard config was applied")
    wireguard_message: Optional[str] = Field(None, description="Message about WireGuard application")


def get_clients_file_path() -> Path:
    """Get the path to wireguard-clients.conf file"""
    # Try multiple possible locations:
    # 1. /app/scripts (Docker container)
    # 2. ./scripts (local development, relative to project root)
    # 3. scripts/ relative to routes/ directory
    
    possible_paths = [
        Path("/app/scripts/wireguard-clients.conf"),  # Docker
        Path("scripts/wireguard-clients.conf"),  # Local (from project root)
        Path(__file__).parent.parent / "scripts" / "wireguard-clients.conf",  # Relative to routes/
    ]
    
    # Check if any parent directory has scripts/
    current = Path(__file__).parent.parent
    while current != current.parent:
        possible_paths.append(current / "scripts" / "wireguard-clients.conf")
        current = current.parent
    
    # Return the first path that exists, or the most likely one
    for path in possible_paths:
        if path.parent.exists():
            return path
    
    # Default to relative path from routes/
    return Path(__file__).parent.parent / "scripts" / "wireguard-clients.conf"


def get_next_available_ip(clients_file: Path) -> int:
    """Find the next available IP suffix"""
    max_ip = 1
    
    if clients_file.exists():
        with open(clients_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line.startswith('#') or not line:
                    continue
                
                # Parse format: MACHINE_ID|CLIENT_NAME|PUBLIC_KEY|IP_SUFFIX (new)
                # or: NAME|PUBLIC_KEY|IP_SUFFIX (old format, backward compat)
                parts = line.split('|')
                if len(parts) >= 4:
                    # New format: MACHINE_ID|CLIENT_NAME|PUBLIC_KEY|IP_SUFFIX
                    try:
                        ip_suffix = int(parts[3])
                        if ip_suffix > max_ip:
                            max_ip = ip_suffix
                    except ValueError:
                        continue
                elif len(parts) >= 3:
                    # Old format: NAME|PUBLIC_KEY|IP_SUFFIX (backward compat)
                    try:
                        ip_suffix = int(parts[2])
                        if ip_suffix > max_ip:
                            max_ip = ip_suffix
                    except ValueError:
                        continue
    
    return max_ip + 1


def update_or_register_client(clients_file: Path, machine_id: str, public_key: str, client_name: str) -> tuple[int, bool]:
    """
    Update existing client or register new one based on machine_id.
    Returns (ip_suffix, is_new_client)
    """
    lines = []
    existing_ip = None
    found = False
    
    # Read existing clients
    if clients_file.exists():
        with open(clients_file, 'r') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('#') or not stripped:
                    lines.append(line)
                    continue
                
                parts = stripped.split('|')
                if len(parts) >= 4 and parts[0].strip() == machine_id:
                    # Found existing machine - update it
                    existing_ip = int(parts[3].strip())
                    lines.append(f"{machine_id}|{client_name}|{public_key}|{existing_ip}\n")
                    found = True
                else:
                    lines.append(line)
    
    # New client - get next IP
    if not found:
        existing_ip = get_next_available_ip(clients_file)
        lines.append(f"{machine_id}|{client_name}|{public_key}|{existing_ip}\n")
    
    # Write back
    clients_file.parent.mkdir(parents=True, exist_ok=True)
    with open(clients_file, 'w') as f:
        f.writelines(lines)
    
    return existing_ip, not found


def apply_wireguard_config() -> tuple[bool, str]:
    """
    Apply WireGuard configuration by running the setup script.
    Returns (success: bool, message: str)
    """
    try:
        # Find the setup script path
        script_paths = [
            Path("/app/scripts/setup-wireguard.sh"),  # Docker
            Path("scripts/setup-wireguard.sh"),  # Local
            Path(__file__).parent.parent / "scripts" / "setup-wireguard.sh",  # Relative
        ]
        
        script_path = None
        for path in script_paths:
            if path.exists() and path.is_file():
                script_path = path
                break
        
        if not script_path:
            return False, "WireGuard setup script not found"
        
        # Make sure script is executable
        os.chmod(script_path, 0o755)
        
        # Ensure SSH directory exists and has correct permissions
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        
        # #region agent log
        with open('/tmp/debug.log', 'a') as f:
            f.write(json.dumps({"location":"provisioning.py:134","message":"SSH dir check","data":{"ssh_dir":str(ssh_dir),"exists":ssh_dir.exists(),"is_dir":ssh_dir.is_dir()},"timestamp":int(time.time()*1000),"sessionId":"debug-session","hypothesisId":"H1"}) + '\n')
        # #endregion
        
        # Fix SSH key permissions (must be 0600 for SSH to accept it)
        # Try both id_rsa and id_ed25519 (user may have either)
        ssh_key = None
        for key_name in ["id_ed25519", "id_rsa"]:
            potential_key = ssh_dir / key_name
            if potential_key.exists() and potential_key.is_file():
                ssh_key = potential_key
                break
        
        if not ssh_key:
            return False, "No SSH key found (checked: id_ed25519, id_rsa)"
        
        # #region agent log
        with open('/tmp/debug.log', 'a') as f:
            f.write(json.dumps({"location":"provisioning.py:141","message":"SSH key check","data":{"ssh_key":str(ssh_key),"exists":ssh_key.exists(),"is_file":ssh_key.is_file(),"is_dir":ssh_key.is_dir(),"stat":str(ssh_key.stat()) if ssh_key.exists() else "N/A"},"timestamp":int(time.time()*1000),"sessionId":"debug-session","hypothesisId":"H2-H3"}) + '\n')
        # #endregion
        
        if ssh_key.exists():
            if ssh_key.is_file():
                os.chmod(ssh_key, 0o600)
                # #region agent log
                with open('/tmp/debug.log', 'a') as f:
                    f.write(json.dumps({"location":"provisioning.py:148","message":"SSH key chmod success","data":{"permissions":"0600"},"timestamp":int(time.time()*1000),"sessionId":"debug-session","hypothesisId":"H4"}) + '\n')
                # #endregion
            else:
                # #region agent log
                with open('/tmp/debug.log', 'a') as f:
                    f.write(json.dumps({"location":"provisioning.py:153","message":"SSH key is NOT a file","data":{"is_dir":ssh_key.is_dir()},"timestamp":int(time.time()*1000),"sessionId":"debug-session","hypothesisId":"H3-CONFIRMED"}) + '\n')
                # #endregion
                return False, f"SSH key exists but is not a file (is_dir={ssh_key.is_dir()})"
        
        # Get the directory containing .env.prod
        # Try multiple locations
        env_file = None
        env_paths = [
            script_path.parent.parent / ".env.prod",  # Relative to scripts/
            Path("/app/.env.prod"),  # Docker container
            Path(".env.prod"),  # Current directory
        ]
        
        for path in env_paths:
            if path.exists():
                env_file = path
                break
        
        if not env_file:
            return False, ".env.prod file not found (checked: " + ", ".join(str(p) for p in env_paths) + ")"
        
        # Run the script (non-blocking, capture output)
        # The script will SSH to remote server and apply config
        result = subprocess.run(
            [str(script_path)],
            capture_output=True,
            text=True,
            timeout=60,  # 60 second timeout
            cwd=str(script_path.parent),
            env={**os.environ, "PATH": os.environ.get("PATH", "")}
        )
        
        if result.returncode == 0:
            return True, "WireGuard configuration applied successfully"
        else:
            error_msg = result.stderr or result.stdout or "Unknown error"
            logger.error(f"WireGuard setup failed: {error_msg}")
            return False, f"Failed to apply WireGuard config: {error_msg[:200]}"
    
    except subprocess.TimeoutExpired:
        return False, "WireGuard setup timed out"
    except Exception as e:
        logger.exception("Error applying WireGuard configuration")
        return False, f"Error applying WireGuard config: {str(e)}"


@router.post("/register", response_model=ProvisionResponse)
async def register_client(
    request: ProvisionRequest = Body(...)
):
    """
    Register a new WireGuard client automatically.
    
    This endpoint receives a public key (Republic Key) and automatically
    registers the client in the WireGuard configuration.
    
    The endpoint is protected by API key authentication.
    """
    try:
        # Validate inputs
        public_key = request.public_key.strip()
        machine_id = request.machine_id.strip()
        
        if not public_key or len(public_key) < 20:
            raise HTTPException(status_code=400, detail="Invalid public key format")
        if not machine_id:
            raise HTTPException(status_code=400, detail="machine_id is required")
        
        # Generate client name if not provided
        client_name = request.client_name or f"client-{machine_id[:8]}"
        
        # Get clients file path
        clients_file = get_clients_file_path()
        
        # Update or register client
        ip_suffix, is_new = update_or_register_client(clients_file, machine_id, public_key, client_name)
        assigned_ip = f"10.0.0.{ip_suffix}"
        
        # Apply WireGuard configuration
        wireguard_success, wireguard_message = apply_wireguard_config()
        
        action = "registered" if is_new else "updated"
        if wireguard_success:
            message = f"Client '{client_name}' {action} and WireGuard configuration applied successfully"
        else:
            message = f"Client '{client_name}' {action} successfully, but WireGuard configuration failed to apply"
            logger.warning(f"Client {action} but WireGuard apply failed: {wireguard_message}")
        
        return ProvisionResponse(
            success=True,
            message=message,
            client_name=client_name,
            client_ip=assigned_ip,
            assigned_ip=assigned_ip,
            wireguard_applied=wireguard_success,
            wireguard_message=wireguard_message
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to register client: {str(e)}"
        )


@router.get("/clients")
async def list_clients():
    """
    List all registered WireGuard clients.
    """
    try:
        clients_file = get_clients_file_path()
        
        if not clients_file.exists():
            return {"clients": [], "total": 0}
        
        clients = []
        with open(clients_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                
                parts = line.split('|')
                if len(parts) >= 4:
                    clients.append({
                        "machine_id": parts[0].strip(),
                        "name": parts[1].strip(),
                        "public_key": parts[2].strip(),
                        "ip": f"10.0.0.{parts[3].strip()}"
                    })
                elif len(parts) >= 3:
                    # Old format support
                    clients.append({
                        "machine_id": "unknown",
                        "name": parts[0].strip(),
                        "public_key": parts[1].strip(),
                        "ip": f"10.0.0.{parts[2].strip()}"
                    })
        
        return {
            "clients": clients,
            "total": len(clients)
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list clients: {str(e)}"
        )
