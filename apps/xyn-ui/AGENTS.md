# AGENTS.md

## xyn-ui Deployment + Git Policy

Apply this workflow for any change made in `xyn-ui`.

### Environment facts
- UI repo path: `/home/ubuntu/src/xyn-ui`
- Remote: `origin https://github.com/Xyence/xyn-ui`
- Branch: `main`
- Production compose file: `/home/ubuntu/src/xyn-api/docker-compose.prod.yml`
- UI service name: `xyn-ui`
- UI container name pattern: `xyn-api-xyn-ui-1`

### Required completion workflow
1. Implement code changes.
2. Validate UI build:
   - `cd /home/ubuntu/src/xyn-ui`
   - `npm run build`
3. Redeploy affected components.
   - If UI changed, redeploy:
     - `docker compose -f /home/ubuntu/src/xyn-api/docker-compose.prod.yml up -d --build xyn-ui`
   - If other services are touched in future, redeploy their corresponding compose services.
4. Verify deployment status:
   - `docker compose -f /home/ubuntu/src/xyn-api/docker-compose.prod.yml ps xyn-ui`
5. Commit and push every completed change:
   - `git -C /home/ubuntu/src/xyn-ui add <changed-files>`
   - `git -C /home/ubuntu/src/xyn-ui commit -m "<clear commit message>"`
   - `git -C /home/ubuntu/src/xyn-ui push origin main`
6. In the final response, report:
   - deployed services
   - commit SHA
   - push result

### Done criteria
Do not stop at code edits only; complete validation, redeploy (when applicable), commit, and push.
