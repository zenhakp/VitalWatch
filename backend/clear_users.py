#!/usr/bin/env python3
"""
Script to clear doctors and patients from the database while preserving admin accounts.
Run from backend directory: python clear_users.py
"""

import asyncio
import sys
from sqlalchemy import select, delete
from app.db.database import async_session_maker
from app.db.models import User, UserRole, VitalReading, Alert, AuditLog, MedicationReminder

async def clear_users(role: str = None):
    """Clear users of a specific role or both doctors and patients."""
    async with async_session_maker() as session:
        try:
            roles_to_clear = []
            if role == "doctors":
                roles_to_clear = [UserRole.doctor]
            elif role == "patients":
                roles_to_clear = [UserRole.patient]
            else:  # Clear both
                roles_to_clear = [UserRole.doctor, UserRole.patient]
            
            # Get all users to delete
            result = await session.execute(
                select(User).where(User.role.in_(roles_to_clear))
            )
            users_to_delete = result.scalars().all()
            user_ids = [str(u.id) for u in users_to_delete]
            
            if not user_ids:
                print(f"No {role or 'doctors/patients'} found to delete.")
                return
            
            print(f"\nClearing {len(user_ids)} {role or 'doctors and patients'}...")
            
            # Delete related records (CASCADE)
            deleted_vitals = await session.execute(
                delete(VitalReading).where(VitalReading.patient_id.in_(user_ids))
            )
            print(f"  ✓ Deleted {deleted_vitals.rowcount} vital readings")
            
            deleted_alerts = await session.execute(
                delete(Alert).where(Alert.patient_id.in_(user_ids))
            )
            print(f"  ✓ Deleted {deleted_alerts.rowcount} alerts")
            
            deleted_meds = await session.execute(
                delete(MedicationReminder)
            )
            print(f"  ✓ Deleted {deleted_meds.rowcount} medication reminders")
            
            # Delete audit logs for these users
            deleted_audit = await session.execute(
                delete(AuditLog).where(AuditLog.user_id.in_(user_ids))
            )
            print(f"  ✓ Deleted {deleted_audit.rowcount} audit log entries")
            
            # Finally, delete the users
            deleted_users = await session.execute(
                delete(User).where(User.role.in_(roles_to_clear))
            )
            print(f"  ✓ Deleted {deleted_users.rowcount} users")
            
            await session.commit()
            print("\n✅ Database cleared successfully!\n")
            
        except Exception as e:
            await session.rollback()
            print(f"\n❌ Error: {e}\n")
            sys.exit(1)

async def main():
    if len(sys.argv) > 1:
        role = sys.argv[1].lower()
        if role not in ["doctors", "patients", "all"]:
            print("Usage: python clear_users.py [doctors|patients|all]")
            print("  doctors  - Clear only doctors")
            print("  patients - Clear only patients")
            print("  all      - Clear both doctors and patients (default)")
            sys.exit(1)
        if role == "all":
            role = None
    else:
        role = None
    
    print("\n" + "="*50)
    print("DATABASE USER CLEANUP")
    print("="*50)
    print(f"Target: {role or 'All Doctors and Patients'}")
    
    confirm = input("\n⚠️  This will permanently delete user records. Continue? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled.\n")
        return
    
    await clear_users(role)

if __name__ == "__main__":
    asyncio.run(main())
