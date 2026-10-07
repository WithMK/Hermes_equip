"""Same-origin local management routes; endpoints/keys are not browser-editable."""
from fastapi import HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from .agent_manager import AgentConflict, AgentMissing


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=120)
    role: str
    instructions: str = Field(default='', max_length=4000)


class CreateProfile(Profile):
    agent_id: str = Field(min_length=1, max_length=64)


class UpdateProfile(Profile):
    version: int = Field(ge=1)


class Version(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: int = Field(ge=1)


class Toggle(Version):
    enabled: bool


def install_agent_routes(app, manager, dispatcher):
    def perform(action):
        try:
            return action()
        except AgentMissing as exc:
            raise HTTPException(404, str(exc)) from exc
        except AgentConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get('/v1/agent-templates')
    def templates():
        return list(manager.templates.values())

    @app.post('/v1/agents', status_code=201)
    def create(value: CreateProfile):
        return perform(lambda: manager.create(**value.model_dump()))

    @app.put('/v1/agents/{agent_id}')
    def update(agent_id: str, value: UpdateProfile):
        return perform(lambda: manager.update(agent_id, **value.model_dump()))

    @app.post('/v1/agents/{agent_id}/enabled')
    def toggle(agent_id: str, value: Toggle):
        return perform(lambda: manager.set_enabled(agent_id, **value.model_dump()))

    @app.post('/v1/agents/{agent_id}/test')
    def test(agent_id: str, value: Version):
        return perform(lambda: manager.test(agent_id, value.version, dispatcher))

    @app.get('/v1/agents/{agent_id}/history')
    def history(agent_id: str):
        return manager.history(agent_id)

    @app.delete('/v1/agents/{agent_id}', status_code=204)
    def delete(agent_id: str, version: int):
        perform(lambda: manager.delete(agent_id, version))
        return Response(status_code=204)
